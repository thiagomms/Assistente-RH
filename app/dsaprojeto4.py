# Projeto 4 - Assistente de RH com Groq, FAISS e RAG

import os
import json
import re
import time
import uuid
import hashlib
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import List

import streamlit as st
import streamlit.components.v1 as components
import docx2txt
import pypdf
import pyodbc
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Carrega variáveis de ambiente
load_dotenv()
groq_api_key = os.getenv("GROQ_API_KEY")

# Observabilidade (LangSmith e Logfire) desativada — evita enviar currículos para serviços externos
os.environ["LANGCHAIN_TRACING_V2"] = "false"

# Caminhos
PASTA_CURRICULOS = Path(__file__).parent / "documentos"
PASTA_STORAGE    = Path(__file__).parent / "storage"
PASTA_FAISS      = PASTA_STORAGE / "faiss_index"
ARQUIVO_CACHE    = Path(__file__).parent / "cache_respostas.json"
SIMILARIDADE_MIN = 0.92
PASTA_CURRICULOS.mkdir(parents=True, exist_ok=True)

# LLM e embeddings (Groq + FastEmbed — igual ao Cap17)
llm          = ChatGroq(api_key=groq_api_key, model="llama-3.3-70b-versatile", temperature=0.1)
llm_rapido   = ChatGroq(api_key=groq_api_key, model="llama-3.1-8b-instant", temperature=0)  # só para classificar intenção
embed_model  = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)


# ── Cache de respostas ──────────────────────────────────────────────────────

def _cache_carregar() -> list:
    if ARQUIVO_CACHE.exists():
        return json.loads(ARQUIVO_CACHE.read_text(encoding="utf-8"))
    return []

def _cache_salvar(cache: list):
    ARQUIVO_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

def _cache_buscar(pergunta: str, categoria: str, vaga_id: str | None, cache: list):
    """Busca no cache: categoria e vaga_id precisam bater EXATAMENTE (nunca
    por similaridade — dois IDs de vaga diferentes não podem 'parecer
    parecidos' só porque o resto do texto é igual). Só o texto da pergunta
    em si usa comparação difusa, e só dentro do mesmo grupo categoria+vaga."""
    p = pergunta.lower().strip()
    for item in cache:
        if item.get("categoria") != categoria or item.get("vaga_id") != vaga_id:
            continue
        ratio = SequenceMatcher(None, p, item["pergunta"].lower().strip()).ratio()
        if ratio >= SIMILARIDADE_MIN:
            return item["resposta"], item.get("fonte")
    return None

def _cache_adicionar(
    pergunta: str, resposta: str, cache: list,
    fonte: str | None = None, categoria: str | None = None, vaga_id: str | None = None,
):
    cache.append({
        "pergunta": pergunta, "categoria": categoria, "vaga_id": vaga_id,
        "resposta": resposta, "fonte": fonte,
    })
    _cache_salvar(cache)


# ── Vagas (Empregare) ───────────────────────────────────────────────────────

ARQUIVO_VAGAS_CACHE = Path(__file__).parent / "vagas_cache.json"

CAMPOS_VAGA = [
    "vaga_id", "id_vaga", "titulo_vaga", "status", "setorNome", "cidade_nome",
    "estado_nome", "regime", "horario", "nivel_hierarquico", "salario_inicial",
    "nome_gestor", "data_cadastro", "descricao", "requisito",
]

def _limpar_html(texto) -> str:
    if not texto:
        return ""
    texto = re.sub(r"<[^>]+>", " ", str(texto))
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto

def _vagas_conectar():
    conn_str = (
        f"DRIVER={{{os.getenv('EMPREGARE_DRIVER')}}};"
        f"SERVER={os.getenv('EMPREGARE_SERVER')};"
        f"DATABASE={os.getenv('EMPREGARE_DB')};"
        f"UID={os.getenv('EMPREGARE_USER')};"
        f"PWD={os.getenv('EMPREGARE_PASSWORD')};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=10)

def _vagas_buscar_do_banco() -> list:
    conn = _vagas_conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM VW_VAGAS_COMPLETAS")
        colunas = [c[0] for c in cur.description]
        vagas = []
        for row in cur.fetchall():
            item = dict(zip(colunas, row))
            item["descricao"] = _limpar_html(item.get("descricao"))
            item["requisito"] = _limpar_html(item.get("requisito"))
            item["vaga_id"] = str(item.get("vaga_id"))
            hash_base = "|".join(str(item.get(c, "")) for c in CAMPOS_VAGA)
            item["hash"] = hashlib.md5(hash_base.encode("utf-8")).hexdigest()
            vagas.append(item)
        return vagas
    finally:
        conn.close()

def _vagas_cache_carregar() -> dict:
    if ARQUIVO_VAGAS_CACHE.exists():
        return json.loads(ARQUIVO_VAGAS_CACHE.read_text(encoding="utf-8"))
    return {"atualizado_em": None, "vagas": []}

def _vagas_cache_salvar(cache: dict):
    ARQUIVO_VAGAS_CACHE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

def atualizar_vagas() -> str:
    cache_antigo = _vagas_cache_carregar()
    antigos_por_id = {v["vaga_id"]: v for v in cache_antigo.get("vagas", [])}

    vagas_novas = _vagas_buscar_do_banco()
    novos_por_id = {v["vaga_id"]: v for v in vagas_novas}

    ids_novos = set(novos_por_id) - set(antigos_por_id)
    ids_removidos = set(antigos_por_id) - set(novos_por_id)
    ids_em_ambos = set(novos_por_id) & set(antigos_por_id)
    ids_alterados = {
        vid for vid in ids_em_ambos
        if novos_por_id[vid].get("hash") != antigos_por_id[vid].get("hash")
    }

    melhores_matches = _melhores_matches_por_vaga(vagas_novas, vector_store) if vector_store is not None else []

    _vagas_cache_salvar({
        "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "vagas": vagas_novas,
        "melhores_matches": melhores_matches,
    })

    partes = []
    if ids_novos:
        partes.append(f"{len(ids_novos)} nova(s)")
    if ids_alterados:
        partes.append(f"{len(ids_alterados)} atualizada(s)")
    if ids_removidos:
        partes.append(f"{len(ids_removidos)} removida(s)")
    return ", ".join(partes) if partes else "nenhuma mudança desde a última atualização"


# ── Carregamento de documentos ──────────────────────────────────────────────

def _fix_spaced_text(text: str) -> str:
    words = text.split()
    if not words:
        return text
    single_char_ratio = sum(1 for w in words if len(w) == 1) / len(words)
    if single_char_ratio < 0.55:
        return text
    result = []
    for segment in re.split(r'  +|\n', text):
        chars = segment.split(' ')
        result.append(''.join(c for c in chars if c))
    return ' '.join(result)

_MARCADORES_INGLES = {"professional summary", "work experience", "education", "skills", "professional experience"}

def _e_ingles(text: str) -> bool:
    lower = text.lower()
    return sum(1 for m in _MARCADORES_INGLES if m in lower) >= 2

def _carregar_documentos(pasta: Path, apenas: set | None = None) -> List[Document]:
    """Lê os currículos e devolve chunks (não o documento inteiro) — necessário
    pro FastEmbed/BGE, que tem limite de 512 tokens, e reduz o tanto de texto
    que vai pro contexto do LLM depois. `apenas`, se informado, restringe a
    leitura a esses nomes de arquivo (usado na indexação incremental)."""
    docs = []
    for pdf in pasta.glob("*.pdf"):
        if apenas is not None and pdf.name not in apenas:
            continue
        try:
            reader = pypdf.PdfReader(str(pdf))
            text = '\n'.join(page.extract_text() or '' for page in reader.pages)
            text = _fix_spaced_text(text)
            if _e_ingles(text):
                text = "[CURRÍCULO EM INGLÊS — PROFISSIONAL DE TI / TECNOLOGIA DA INFORMAÇÃO]\n" + text
            if text.strip():
                docs.append(Document(page_content=text, metadata={"file_name": pdf.name}))
        except Exception as e:
            st.warning(f"Erro ao ler {pdf.name}: {e}")
    for docx_file in pasta.glob("*.docx"):
        if apenas is not None and docx_file.name not in apenas:
            continue
        try:
            text = docx2txt.process(str(docx_file))
            if text.strip():
                docs.append(Document(page_content=text, metadata={"file_name": docx_file.name}))
        except Exception as e:
            st.warning(f"Erro ao ler {docx_file.name}: {e}")
    return text_splitter.split_documents(docs)


# ── Índice FAISS ────────────────────────────────────────────────────────────

ARQUIVO_INDEXADOS = PASTA_STORAGE / "indexados.json"  # {nome_arquivo: [ids_dos_chunks_no_faiss]}
ARQUIVO_LOCK      = PASTA_STORAGE / ".reindex.lock"
LOCK_TIMEOUT      = 30  # segundos

def _carregar_indexados() -> dict:
    if ARQUIVO_INDEXADOS.exists():
        return json.loads(ARQUIVO_INDEXADOS.read_text(encoding="utf-8"))
    return {}

def _salvar_indexados(mapa: dict):
    ARQUIVO_INDEXADOS.write_text(json.dumps(mapa, ensure_ascii=False, indent=2), encoding="utf-8")

def _arquivos_atuais() -> set:
    return {f.name for f in PASTA_CURRICULOS.glob("*.pdf")} | {f.name for f in PASTA_CURRICULOS.glob("*.docx")}

def _lock_adquirir(timeout: int = LOCK_TIMEOUT) -> bool:
    """Evita que duas sessões reindexem ao mesmo tempo (ex: dois uploads
    simultâneos). Se o lock já existir, espera até `timeout`s; se continuar
    preso, desiste e quem chamou usa o índice salvo como está."""
    inicio = time.time()
    while ARQUIVO_LOCK.exists():
        if time.time() - inicio > timeout:
            return False
        time.sleep(0.5)
    ARQUIVO_LOCK.touch()
    return True

def _lock_liberar():
    ARQUIVO_LOCK.unlink(missing_ok=True)

@st.cache_resource(show_spinner=False)
def dsa_modulo_rag():
    arquivos_atuais = _arquivos_atuais()
    if not arquivos_atuais:
        return None

    PASTA_STORAGE.mkdir(parents=True, exist_ok=True)
    indexados = _carregar_indexados()

    if PASTA_FAISS.exists() and set(indexados) == arquivos_atuais:
        with st.spinner("Carregando índice salvo..."):
            return FAISS.load_local(str(PASTA_FAISS), embed_model, allow_dangerous_deserialization=True)

    if not _lock_adquirir():
        if PASTA_FAISS.exists():
            return FAISS.load_local(str(PASTA_FAISS), embed_model, allow_dangerous_deserialization=True)
        return None

    try:
        vector_store = (
            FAISS.load_local(str(PASTA_FAISS), embed_model, allow_dangerous_deserialization=True)
            if PASTA_FAISS.exists() else None
        )

        removidos = set(indexados) - arquivos_atuais
        if removidos and vector_store is not None:
            ids_remover = [vid for nome in removidos for vid in indexados.get(nome, [])]
            if ids_remover:
                vector_store.delete(ids_remover)
        for nome in removidos:
            indexados.pop(nome, None)

        novos = arquivos_atuais - set(indexados)
        if novos:
            with st.spinner(f"Criando vetores de {len(novos)} currículo(s) novo(s) – aguarde..."):
                chunks_novos = _carregar_documentos(PASTA_CURRICULOS, apenas=novos)
                if chunks_novos:
                    ids_novos = [str(uuid.uuid4()) for _ in chunks_novos]
                    if vector_store is None:
                        vector_store = FAISS.from_documents(chunks_novos, embed_model, ids=ids_novos)
                    else:
                        vector_store.add_documents(chunks_novos, ids=ids_novos)
                    for doc, vid in zip(chunks_novos, ids_novos):
                        indexados.setdefault(doc.metadata["file_name"], []).append(vid)

        if vector_store is None:
            return None

        vector_store.save_local(str(PASTA_FAISS))
        _salvar_indexados(indexados)
        return vector_store
    finally:
        _lock_liberar()

def reindexar():
    dsa_modulo_rag.clear()
    if "retriever" in st.session_state:
        del st.session_state["retriever"]
    st.rerun()


# ── Geração de resposta com RAG ─────────────────────────────────────────────

MAX_HISTORICO = 10  # ultimas N mensagens (pergunta+resposta) consideradas como contexto da conversa

def _historico_para_mensagens(mensagens: list) -> list:
    convertidas = []
    for m in mensagens[-MAX_HISTORICO:]:
        if m["role"] == "user":
            convertidas.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            convertidas.append(AIMessage(content=m["content"]))
    return convertidas

MAX_MENSAGENS_BUSCA = 8  # ultimas mensagens (pergunta+resposta) que entram na busca do FAISS

def _consulta_busca(pergunta: str, historico: list) -> str:
    """Monta a query de busca no FAISS combinando a pergunta atual com as
    últimas mensagens da conversa (perguntas E respostas). As respostas
    anteriores costumam citar o nome do candidato por extenso, o que ajuda
    a busca semântica a reconectar pronomes ('ele', 'o segundo') ao
    currículo certo em perguntas de acompanhamento."""
    recentes = [m["content"] for m in historico[-MAX_MENSAGENS_BUSCA:]]
    return "\n".join(recentes + [pergunta])

def _chamar_llm(system_template: str, variaveis: dict, pergunta: str, historico: list, modelo=None) -> str:
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template),
        MessagesPlaceholder(variable_name="historico"),
        ("human", "{pergunta}")
    ])
    chain = prompt | (modelo or llm) | StrOutputParser()
    return chain.invoke({
        **variaveis,
        "pergunta": pergunta,
        "historico": _historico_para_mensagens(historico),
    })

def dsa_gerar_resposta(pergunta: str, retriever, historico: list) -> str:
    docs = retriever.invoke(_consulta_busca(pergunta, historico))
    contexto = "\n\n".join([d.page_content for d in docs])

    system = (
        "Você é um assistente de RH especializado em análise de currículos. "
        "Responda SOMENTE em português do Brasil. "
        "Use apenas as informações dos currículos fornecidos abaixo. "
        "Considere o histórico da conversa para entender perguntas de "
        "acompanhamento (ex: 'e o segundo?', 'ele tem inglês?'). "
        "Seja objetivo e claro, máximo 5 frases.\n\n"
        "Currículos:\n{contexto}"
    )
    return _chamar_llm(system, {"contexto": contexto}, pergunta, historico)


# ── Geração de resposta — Vagas ─────────────────────────────────────────────

CATEGORIAS_VALIDAS = {"vaga_especifica", "match", "vagas_geral", "curriculo"}

def _classificar_intencao(pergunta: str, historico: list, vagas: list) -> dict:
    """Chamada dedicada ao LLM só pra decidir o roteamento (não gera a
    resposta final). Mais robusto que lista de palavras-chave: entende
    qualquer jeito de perguntar e resolve referências ('essa vaga', 'ele')
    usando o histórico da conversa."""
    ids_vagas = ", ".join(v["vaga_id"] for v in vagas) if vagas else "(nenhuma vaga carregada ainda)"
    system = (
        "Classifique a MENSAGEM MAIS RECENTE do usuário (a última da conversa) em UMA categoria:\n"
        "- vaga_especifica: pergunta sobre detalhes de UMA vaga (requisitos, local, status etc.), "
        "sem pedir comparação com candidatos\n"
        "- match: pede pra cruzar candidato(s)/currículo(s) com vaga(s) — em QUALQUER direção: "
        "'quem é o melhor candidato pra essa vaga' OU 'em qual vaga ele se encaixa' OU "
        "'esse candidato serve pra alguma vaga em aberto'\n"
        "- vagas_geral: pergunta sobre vagas em geral (lista, quantidade, filtro por área/cidade/status)\n"
        "- curriculo: pergunta sobre candidatos/currículos SEM relação com nenhuma vaga\n\n"
        "Use o restante da conversa para resolver referências como 'essa vaga', 'ele', 'o segundo'. "
        "Se a categoria for vaga_especifica, ou for match E uma vaga específica já estiver clara pela "
        "conversa, identifique o ID dela (usando o histórico se necessário). Se for match mas a vaga "
        "ainda não foi definida (ex: perguntando em qual vaga um candidato se encaixa, sem vaga "
        f"específica em mente), deixe VAGA_ID como nenhum. IDs de vaga válidos: {ids_vagas}\n\n"
        "Responda EXATAMENTE no formato abaixo, sem nenhum texto a mais:\n"
        "CATEGORIA: <vaga_especifica|match|vagas_geral|curriculo>\n"
        "VAGA_ID: <id da vaga ou nenhum>"
    )
    resposta = _chamar_llm(system, {}, pergunta, historico, modelo=llm_rapido)

    categoria = "curriculo"
    m_cat = re.search(r"CATEGORIA:\s*(\w+)", resposta, re.IGNORECASE)
    if m_cat and m_cat.group(1).lower() in CATEGORIAS_VALIDAS:
        categoria = m_cat.group(1).lower()

    vaga_id = None
    m_id = re.search(r"VAGA_ID:\s*(\S+)", resposta, re.IGNORECASE)
    if m_id and m_id.group(1).lower() not in {"nenhum", "none", "null", "-"}:
        vaga_id = m_id.group(1).strip()

    return {"categoria": categoria, "vaga_id": vaga_id}

def dsa_gerar_resposta_vaga_especifica(pergunta: str, vaga: dict, historico: list) -> str:
    contexto = (
        f"ID: {vaga.get('vaga_id')}\n"
        f"Título: {vaga.get('titulo_vaga')}\n"
        f"Status: {vaga.get('status')}\n"
        f"Setor: {vaga.get('setorNome')}\n"
        f"Local: {vaga.get('cidade_nome')}/{vaga.get('estado_nome')}\n"
        f"Regime: {vaga.get('regime')}\n"
        f"Horário: {vaga.get('horario')}\n"
        f"Nível: {vaga.get('nivel_hierarquico')}\n"
        f"Gestor responsável: {vaga.get('nome_gestor')}\n"
        f"Cadastrada em: {vaga.get('data_cadastro')}\n\n"
        f"Descrição: {vaga.get('descricao')}\n\n"
        f"Requisitos: {vaga.get('requisito')}"
    )
    system = (
        "Você é um assistente de RH especializado em vagas. "
        "Responda SOMENTE em português do Brasil, com base apenas nos dados "
        "da vaga fornecidos abaixo. Traga detalhes completos (descrição, "
        "requisitos, local, regime) quando fizer sentido para a pergunta.\n\n"
        "Vaga:\n{contexto}"
    )
    return _chamar_llm(system, {"contexto": contexto}, pergunta, historico)

def dsa_gerar_resposta_vagas_geral(pergunta: str, vagas: list, historico: list) -> str:
    linhas = [
        f"- ID {v.get('vaga_id')}: {v.get('titulo_vaga')} | Status: {v.get('status')} | "
        f"Setor: {v.get('setorNome')} | Local: {v.get('cidade_nome')}/{v.get('estado_nome')} | "
        f"Regime: {v.get('regime')}"
        for v in vagas
    ]
    contexto = "\n".join(linhas) if linhas else "Nenhuma vaga disponível."
    system = (
        "Você é um assistente de RH especializado em vagas. "
        "Responda SOMENTE em português do Brasil, com base apenas na lista de "
        "vagas fornecida abaixo. Se fizer sentido, sugira que perguntem pelo "
        "ID de uma vaga específica para obter detalhes completos. "
        "Seja objetivo, máximo 6 frases.\n\n"
        "Vagas:\n{contexto}"
    )
    return _chamar_llm(system, {"contexto": contexto}, pergunta, historico)

def dsa_gerar_resposta_match(pergunta: str, vaga: dict, retriever, historico: list) -> str:
    """Cruza os requisitos de uma vaga específica com os currículos indexados,
    pra responder perguntas do tipo 'quem é o melhor candidato pra essa vaga'."""
    consulta = f"{vaga.get('titulo_vaga', '')} {vaga.get('requisito', '')}"
    docs = retriever.invoke(consulta)
    contexto_curriculos = "\n\n".join(d.page_content for d in docs)
    contexto_vaga = (
        f"Título: {vaga.get('titulo_vaga')}\n"
        f"Requisitos: {vaga.get('requisito')}\n"
        f"Descrição: {vaga.get('descricao')}\n"
        f"Local: {vaga.get('cidade_nome')}/{vaga.get('estado_nome')} | Regime: {vaga.get('regime')}"
    )
    system = (
        "Você é um assistente de RH especializado em recrutamento. "
        "Responda SOMENTE em português do Brasil. "
        "Compare os requisitos da vaga abaixo com os currículos fornecidos e "
        "indique o(s) candidato(s) mais adequados, explicando brevemente o "
        "porquê com base nos requisitos da vaga. Se nenhum currículo for "
        "compatível, diga isso claramente. Seja objetivo, máximo 6 frases.\n\n"
        "Vaga:\n{contexto_vaga}\n\n"
        "Currículos disponíveis:\n{contexto_curriculos}"
    )
    return _chamar_llm(
        system,
        {"contexto_vaga": contexto_vaga, "contexto_curriculos": contexto_curriculos},
        pergunta, historico,
    )

def dsa_gerar_resposta_match_reverso(pergunta: str, retriever, vagas: list, historico: list) -> str:
    """Direção inversa do match: dado um candidato (identificado pelo contexto
    da conversa), diz em quais vagas reais ele se encaixa. A lista de vagas
    vai inteira no prompt pra IA nunca inventar uma vaga que não existe."""
    docs = retriever.invoke(_consulta_busca(pergunta, historico))
    contexto_curriculo = "\n\n".join(d.page_content for d in docs)

    vagas_relevantes = [v for v in vagas if v.get("status") == "Aberta"] or vagas
    linhas = [
        f"- ID {v.get('vaga_id')}: {v.get('titulo_vaga')} | Status: {v.get('status')} | "
        f"Setor: {v.get('setorNome')} | Local: {v.get('cidade_nome')}/{v.get('estado_nome')} | "
        f"Requisitos: {(v.get('requisito') or '')[:300]}"
        for v in vagas_relevantes
    ]
    contexto_vagas = "\n".join(linhas) if linhas else "Nenhuma vaga disponível."

    system = (
        "Você é um assistente de RH especializado em recrutamento. "
        "Responda SOMENTE em português do Brasil. "
        "Com base no(s) currículo(s) fornecido(s) abaixo e na lista de vagas "
        "reais fornecida, diga em qual(is) vaga(s) o candidato discutido na "
        "conversa se encaixa melhor, e por quê. USE APENAS as vagas listadas "
        "abaixo — NUNCA invente ou cite uma vaga que não esteja na lista. Se "
        "nenhuma vaga combinar bem, diga isso claramente. Seja objetivo, "
        "máximo 6 frases.\n\n"
        "Currículo(s):\n{contexto_curriculo}\n\n"
        "Vagas disponíveis (reais):\n{contexto_vagas}"
    )
    return _chamar_llm(
        system,
        {"contexto_curriculo": contexto_curriculo, "contexto_vagas": contexto_vagas},
        pergunta, historico,
    )


# ── Interface Streamlit ─────────────────────────────────────────────────────

st.set_page_config(
    page_title="Assistente de RH",
    page_icon=str(Path(__file__).parent / "favicon.png"),
    layout="centered",
)
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"] p {font-size: 0.9rem;}
    [data-testid="stMainBlockContainer"] {padding-top: 1.5rem;}
    </style>
""", unsafe_allow_html=True)

components.html("""
    <script>
    function traduzirUploader() {
        const doc = window.parent.document;
        doc.querySelectorAll('button').forEach(btn => {
            if (btn.textContent.trim() === 'Browse files') {
                btn.textContent = 'Upload';
            }
        });
        doc.querySelectorAll('span').forEach(el => {
            if (el.children.length === 0 && el.textContent.trim() === 'Drag and drop files here') {
                el.textContent = 'Arraste e solte os arquivos aqui';
            }
        });
        doc.querySelectorAll('small').forEach(el => {
            if (el.textContent.includes('Limit') && el.textContent.includes('per file')) {
                el.textContent = el.textContent.replace('Limit', 'Limite').replace(' per file', '');
            }
        });
        doc.querySelectorAll('[data-testid="stFileUploaderPagination"] span').forEach(el => {
            const m = el.textContent.match(/Showing page (\d+) of (\d+)/);
            if (m) {
                el.textContent = `Página ${m[1]} de ${m[2]}`;
            }
        });
    }
    traduzirUploader();
    const alvo = window.parent.document.body;
    new MutationObserver(traduzirUploader).observe(alvo, {childList: true, subtree: true});
    </script>
""", height=0)

# Carrega RAG e retriever (disponível para as duas páginas, não só o chat)
vector_store = dsa_modulo_rag()
if vector_store is not None:
    if "retriever" not in st.session_state:
        st.session_state.retriever = vector_store.as_retriever(search_kwargs={"k": 5})
else:
    st.session_state.pop("retriever", None)

def pagina_chat():
    # Barra lateral
    st.sidebar.image(str(Path(__file__).parent / "logo.webp.png"), use_container_width=True)
    st.sidebar.markdown("---")
    st.sidebar.title("Instruções")
    st.sidebar.write("""
    - Faça upload dos currículos abaixo (`.pdf` ou `.docx`).
    - Os arquivos são salvos em `documentos/` dentro do projeto.
    - Digite perguntas sobre os candidatos ou sobre as vagas no chat.
    - Para detalhes de uma vaga específica, cite o ID dela na pergunta.
    - Quanto mais detalhada for a pergunta, melhor a resposta.
    - Recomenda-se limpar o cache ao iniciar uma nova conversa.

    **Atenção:** IA Generativa pode cometer erros, sempre valide as informações!
    """)

    st.sidebar.markdown("---")
    st.sidebar.subheader("Adicionar Currículos")
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0

    arquivos_enviados = st.sidebar.file_uploader(
        "Selecione os currículos",
        type=["pdf", "docx"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key=f"uploader_{st.session_state.uploader_key}"
    )

    if arquivos_enviados:
        hashes_existentes = {
            hashlib.md5(f.read_bytes()).hexdigest()
            for f in list(PASTA_CURRICULOS.glob("*.pdf")) + list(PASTA_CURRICULOS.glob("*.docx"))
        }
        novos_arquivos = []
        duplicados = []
        for arquivo in arquivos_enviados:
            dados = arquivo.read()
            hash_arquivo = hashlib.md5(dados).hexdigest()
            if hash_arquivo in hashes_existentes:
                duplicados.append(arquivo.name)
                continue
            destino = PASTA_CURRICULOS / arquivo.name
            if destino.exists():
                destino = PASTA_CURRICULOS / f"{destino.stem}_{hash_arquivo[:6]}{destino.suffix}"
            destino.write_bytes(dados)
            hashes_existentes.add(hash_arquivo)
            novos_arquivos.append(destino.name)

        if duplicados:
            st.sidebar.warning(f"Currículo(s) repetido(s), não anexado(s): {', '.join(duplicados)}")
        if novos_arquivos:
            st.sidebar.success(f"{len(novos_arquivos)} currículo(s) salvo(s)! Reindexando...")
            st.session_state.uploader_key += 1
            reindexar()

    curriculos_salvos = list(PASTA_CURRICULOS.glob("*.pdf")) + list(PASTA_CURRICULOS.glob("*.docx"))
    if curriculos_salvos:
        st.sidebar.markdown("---")
        st.sidebar.subheader(f"Currículos na pasta ({len(curriculos_salvos)})")
        for c in curriculos_salvos:
            col_nome, col_lixeira = st.sidebar.columns([3, 2], vertical_alignment="center")
            col_nome.download_button(
                label=c.name,
                data=c.read_bytes(),
                file_name=c.name,
                key=f"baixar_{c.name}",
                help=f"Abrir/baixar {c.name}",
                type="tertiary",
            )
            if col_lixeira.button("remover", key=f"remover_{c.name}", help=f"Remover {c.name}", type="tertiary"):
                c.unlink()
                reindexar()

    st.sidebar.markdown("---")
    cache_atual = _cache_carregar()
    n_cache = len(cache_atual)
    if st.sidebar.button(f"Limpar Cache ({n_cache} respostas)", help="Apaga as respostas armazenadas"):
        _cache_salvar([])
        st.sidebar.success("Cache limpo!")
        st.rerun()

    st.sidebar.markdown("---")
    if st.sidebar.button("Suporte"):
        st.sidebar.write("Dúvidas? Envie um e-mail para: guilherme.martins@brasiliaseg.com.br")

    # Título
    st.title("Assistente de RH")
    st.subheader("Currículos e Vagas com IA (Groq + RAG + FAISS)")

    # Histórico
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Olá! Faça sua pergunta sobre os currículos ou sobre as vagas."}
        ]

    if vector_store is None:
        st.info("Nenhum currículo carregado ainda. Faça upload na barra lateral, ou pergunte sobre vagas.")

    # Input
    prompt = st.chat_input("Sua pergunta sobre os currículos ou vagas")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})

    # Exibe histórico
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    # Gera resposta
    if st.session_state.messages[-1]["role"] != "assistant":
        with st.chat_message("assistant"):
            user_message = st.session_state.messages[-1]["content"]
            historico = st.session_state.messages[:-1]
            vagas_cache = _vagas_cache_carregar()
            vagas_lista = vagas_cache.get("vagas", [])
            por_id = {v["vaga_id"]: v for v in vagas_lista}

            with st.spinner("Identificando o assunto da pergunta..."):
                classificacao = _classificar_intencao(user_message, historico, vagas_lista)
            categoria = classificacao["categoria"]
            vaga_alvo = por_id.get(classificacao["vaga_id"])

            vaga_id_resolvido = classificacao["vaga_id"]
            cache_atual = _cache_carregar()
            resultado_cache = _cache_buscar(user_message, categoria, vaga_id_resolvido, cache_atual)

            if resultado_cache:
                resposta_texto, fonte_cache = resultado_cache
                st.write(resposta_texto)
                st.caption(f"⚡ Resposta do cache — {fonte_cache}" if fonte_cache else "⚡ Resposta do cache")
                st.session_state.messages.append({"role": "assistant", "content": resposta_texto})
            else:
                with st.status("Consultando...") as status:
                    if categoria in ("vaga_especifica", "match") and not vagas_lista:
                        resposta = (
                            "Ainda não há vagas carregadas. Peça para alguém clicar em "
                            "**Atualizar Vagas** na página de Vagas primeiro."
                        )
                        fonte = None
                    elif categoria == "match" and vaga_alvo and vector_store is not None:
                        st.write("Cruzando requisitos da vaga com os currículos...")
                        resposta = dsa_gerar_resposta_match(
                            user_message, vaga_alvo, st.session_state.retriever, historico
                        )
                        fonte = f"📄💼 Fonte: Vaga #{vaga_alvo['vaga_id']} + Currículos indexados"
                    elif categoria == "match" and vector_store is None:
                        resposta = "Nenhum currículo carregado ainda pra comparar com a vaga. Faça upload na barra lateral."
                        fonte = None
                    elif categoria == "match" and vector_store is not None:
                        st.write("Cruzando o candidato discutido com as vagas em aberto...")
                        resposta = dsa_gerar_resposta_match_reverso(
                            user_message, st.session_state.retriever, vagas_lista, historico
                        )
                        fonte = f"📄💼 Fonte: Currículos indexados + Vagas (atualizado em {vagas_cache.get('atualizado_em')})"
                    elif categoria == "vaga_especifica" and vaga_alvo:
                        st.write("Buscando detalhes da vaga no cache local...")
                        resposta = dsa_gerar_resposta_vaga_especifica(user_message, vaga_alvo, historico)
                        fonte = f"💼 Fonte: Vaga #{vaga_alvo['vaga_id']} (atualizado em {vagas_cache.get('atualizado_em')})"
                    elif categoria == "vagas_geral":
                        st.write("Buscando nas vagas (cache local)...")
                        resposta = dsa_gerar_resposta_vagas_geral(user_message, vagas_lista, historico)
                        fonte = f"💼 Fonte: Vagas (atualizado em {vagas_cache.get('atualizado_em')})"
                    elif vector_store is not None:
                        st.write("Buscando nos currículos (FAISS + RAG)...")
                        resposta = dsa_gerar_resposta(user_message, st.session_state.retriever, historico)
                        fonte = "📄 Fonte: Currículos indexados"
                    else:
                        resposta = "Nenhum currículo carregado ainda. Faça upload na barra lateral, ou pergunte sobre vagas."
                        fonte = None
                    status.update(label="Resposta pronta!", state="complete")

                st.write(resposta)
                if fonte:
                    st.caption(fonte)
                _cache_adicionar(user_message, resposta, cache_atual, fonte, categoria, vaga_id_resolvido)
                st.session_state.messages.append({"role": "assistant", "content": resposta})


def _nome_amigavel(nome_arquivo: str) -> str:
    nome = Path(nome_arquivo).stem
    nome = re.sub(r"^curriculo[_-]?", "", nome, flags=re.IGNORECASE)
    nome = re.sub(r"[_-]+", " ", nome).strip()
    return nome.title() or nome_arquivo

def _melhores_matches_por_vaga(vagas: list, vector_store, max_vagas: int = 8) -> list:
    """Pra cada vaga em aberto, acha o currículo mais próximo por similaridade
    (busca local no FAISS, sem chamar o LLM — rápido e sem custo de API)."""
    abertas = [v for v in vagas if v.get("status") == "Aberta"]
    resultados = []
    for v in abertas:
        consulta = f"{v.get('titulo_vaga', '')} {v.get('requisito', '')}"
        try:
            docs_scores = vector_store.similarity_search_with_score(consulta, k=1)
        except Exception:
            continue
        if not docs_scores:
            continue
        doc, score = docs_scores[0]
        resultados.append({
            "vaga_id": v.get("vaga_id"),
            "titulo_vaga": v.get("titulo_vaga"),
            "candidato": _nome_amigavel(doc.metadata.get("file_name", "—")),
            "score": score,
        })
    resultados.sort(key=lambda r: r["score"])
    return resultados[:max_vagas]

def pagina_vagas():
    st.sidebar.image(str(Path(__file__).parent / "logo.webp.png"), use_container_width=True)
    st.sidebar.markdown("---")
    st.sidebar.subheader("Melhores matches")
    st.sidebar.caption("Currículo mais próximo de cada vaga em aberto (calculado no último Atualizar Vagas)")
    cache_lateral = _vagas_cache_carregar()
    matches = cache_lateral.get("melhores_matches", [])
    if not cache_lateral.get("vagas"):
        st.sidebar.caption("Atualize as vagas para ver os matches.")
    elif not matches:
        st.sidebar.caption("Nenhuma vaga em aberto, ou nenhum currículo carregado.")
    else:
        for m in matches:
            st.sidebar.markdown(f"**{m['titulo_vaga']}** _(#{m['vaga_id']})_")
            st.sidebar.write(f"→ {m['candidato']}")

    st.title("Vagas")
    st.subheader("Vagas cadastradas no Empregare")

    cache = _vagas_cache_carregar()
    vagas = cache.get("vagas", [])
    atualizado_em = cache.get("atualizado_em")

    col_info, col_botao = st.columns([3, 1], vertical_alignment="center")
    with col_info:
        st.caption(f"Última atualização: {atualizado_em}" if atualizado_em else "Nunca atualizado ainda.")
    with col_botao:
        if st.button("🔄 Atualizar Vagas"):
            with st.spinner("Buscando vagas no banco..."):
                try:
                    resumo = atualizar_vagas()
                    st.success(f"Atualizado! {resumo}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Não foi possível atualizar as vagas: {e}")

    if not vagas:
        st.info("Nenhuma vaga carregada ainda. Clique em **Atualizar Vagas** para buscar do banco.")
        return

    status_disponiveis = sorted({v.get("status", "—") for v in vagas})
    padrao = [s for s in status_disponiveis if s == "Aberta"] or status_disponiveis
    status_selecionados = st.multiselect("Status", options=status_disponiveis, default=padrao)

    vagas_filtradas = [v for v in vagas if v.get("status") in status_selecionados]
    st.caption(f"{len(vagas_filtradas)} vaga(s) encontrada(s)")

    for v in vagas_filtradas:
        titulo = f"#{v.get('vaga_id')} — {v.get('titulo_vaga')} ({v.get('status')})"
        with st.expander(titulo):
            st.write(f"**Setor:** {v.get('setorNome') or '—'}")
            st.write(f"**Local:** {v.get('cidade_nome') or '—'}/{v.get('estado_nome') or '—'}")
            st.write(f"**Regime:** {v.get('regime') or '—'}  •  **Horário:** {v.get('horario') or '—'}")
            st.write(f"**Nível:** {v.get('nivel_hierarquico') or '—'}")
            st.write(f"**Gestor:** {v.get('nome_gestor') or '—'}")
            st.write(f"**Cadastrada em:** {v.get('data_cadastro') or '—'}")
            st.markdown("**Descrição**")
            st.write(v.get("descricao") or "—")
            st.markdown("**Requisitos**")
            st.write(v.get("requisito") or "—")


pagina_atual = st.navigation([
    st.Page(pagina_chat, title="Assistente de RH", icon="💬", default=True),
    st.Page(pagina_vagas, title="Vagas Empregare", icon="💼"),
])
pagina_atual.run()
