# Otimizações — Assistente de RH

Guia com o diagnóstico do consumo alto de CPU/tokens e o plano de correção.
Rodar quando tiver tempo (não é urgente, mas resolve o problema do dia dos testes).

---

## Diagnóstico — por que a VM foi a 100% de CPU

O gargalo **não é ler os PDFs**, é gerar os embeddings com FastEmbed (modelo BGE),
que roda 100% na CPU. Três gatilhos no código atual multiplicam o problema:

### 1. Reindexação total a cada upload (`dsaprojeto4.py:242-251`)

```python
if PASTA_STORAGE.exists():
    shutil.rmtree(PASTA_STORAGE)  # apaga TUDO
docs = _carregar_documentos(PASTA_CURRICULOS)  # relê TUDO
vector_store = FAISS.from_documents(docs, embed_model)  # reembeda TUDO
```

Se alguém sobe 20 currículos **um por um**, o app reprocessa em cascata:
`1 + 2 + 3 + ... + 20 = 210 embeddings` em vez de 20. Trava a VM.

### 2. Cada currículo vira 1 Document único, sem chunking

Currículo de 3 páginas = ~3000 tokens. O BGE tem limite de 512 tokens — o FastEmbed
trunca ou divide internamente, gastando mais CPU e piorando a qualidade da busca.

### 3. `@st.cache_resource` só cacheia por sessão

Múltiplos usuários abrindo o app ao mesmo tempo, enquanto o índice está sendo criado,
podem disparar reindexações **paralelas** — CPU multiplicada por N usuários.

### Como confirmar

Ver `log.txt` no dia dos testes. Se aparecerem várias mensagens
"Criando vetores dos currículos" seguidas → reindexação em cascata confirmada.

---

## FAISS vs numpy — não muda nada nesse caso

Para ~19 currículos (situação atual):
- **numpy** (`X @ q.T` cosine): ~0.1ms
- **FAISS**: ~0.1ms

FAISS só ganha a partir de ~10.000 vetores. Manter FAISS — trocar por numpy não
resolve o problema de CPU (que está no embedding, não na busca) e perderia
`save_local`/`load_local` e integração com LangChain.

---

## Consumo de tokens (Groq) — o que realmente impacta

Tokens são gastos no que vai pro Groq (contexto + pergunta + resposta). A busca
vetorial é 100% local, não gasta token.

| Onde vaza token hoje | Impacto | Fix |
|---|---|---|
| `k=5` currículos inteiros no contexto (`:515`) — cada PDF é 1 Document sem chunking | 🔴 Alto — 20k+ tokens/pergunta | Chunkar (500-800 tokens) e recuperar 4-6 chunks |
| `_classificar_intencao` faz 1 chamada extra ao LLM só pra rotear (`:319-355`) | 🟡 Médio — dobra latência | Usar `llama-3.1-8b-instant` só nessa etapa |
| `MAX_HISTORICO=10` mensagens no prompt (`:264`) | 🟡 Médio | OK pra chat, cortar respostas antigas longas |
| `match_reverso` manda TODAS as vagas no prompt (`:441`) | 🔴 Alto se muitas vagas | Filtrar top-N por similaridade antes |

---

## Plano de correção — em ordem de impacto

### 1. Indexação incremental (corta ~90% da CPU)
Só embedar arquivos novos, não apagar `storage/` a cada upload.
Manter um map `{nome_arquivo: [ids_dos_vetores]}` pra saber o que já foi indexado.

### 2. Debounce no upload
Se o usuário sobe 10 arquivos, esperar todos entrarem antes de reindexar
(uma reindexação só, não 10).

### 3. Chunking dos currículos
`RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)`.
Reduz ~70% dos tokens no contexto e cada embedding cabe no limite do BGE.

**Atualização pós-teste em VM (2026-07-27):** a ideia original era reduzir
`k=5` → `k=3` depois do chunking. Revertido para `k=5` — com chunks menores
e conversas de vários turnos, `_consulta_busca` mistura a pergunta atual com
respostas anteriores do assistente (proposital, ajuda a resolver "e o
segundo?"). Se uma resposta anterior estiver errada, esse texto errado entra
na busca seguinte e empurra o currículo certo pra fora do top-3 — a IA
reforça o próprio erro. Com `k=5` sobra margem pra isso não acontecer.
Testado com o caso real "Thiago Almeida": com `k=3` o currículo certo caía
pra 4º lugar no ranking (fora do corte); com `k=5` entra. O chunking sozinho
já entrega a maior parte da economia de tokens, então não vale reduzir `k`
por cima disso.

### 4. Lock de reindexação
Arquivo `.lock` no `storage/` pra impedir 2 processos reindexarem juntos.

### 5. Modelo menor para classificar intenção
Trocar `llama-3.3-70b-versatile` por `llama-3.1-8b-instant` **só** em
`_classificar_intencao`. A geração final continua no 70B.

Estimativa combinada: **~60% menos tokens + ~90% menos CPU em picos de upload**.

---

## Prompt pronto para rodar depois

Copie e cole no Claude Code quando for aplicar:

```
Aplique as otimizações descritas em OTIMIZACOES.md no arquivo dsaprojeto4.py,
nesta ordem:

1. Indexação incremental — não apagar storage/ a cada upload. Manter um JSON
   {nome_arquivo: [ids_dos_vetores]} em storage/indexados.json. Ao reindexar,
   só embedar arquivos novos e remover vetores de arquivos que sumiram da pasta
   documentos/. Usar vector_store.add_documents() e vector_store.delete().

2. Chunking — usar RecursiveCharacterTextSplitter(chunk_size=800,
   chunk_overlap=100) em _carregar_documentos, mantendo o metadata file_name
   em cada chunk. Reduzir search_kwargs de k=5 para k=3.

3. Lock de reindexação — criar storage/.reindex.lock antes de indexar e
   remover no fim (try/finally). Se o lock existir, esperar até 30s ou pular.

4. Modelo menor para classificar — em _classificar_intencao, usar uma
   segunda instância de ChatGroq com model="llama-3.1-8b-instant" e
   temperature=0. A geração das respostas continua no llama-3.3-70b-versatile.

5. Debounce no upload — quando o file_uploader receber múltiplos arquivos de
   uma vez, salvar todos primeiro e chamar reindexar() UMA vez só no final
   (já é assim, só confirmar que reindexar() não é chamado dentro do loop).

Antes de mexer, leia dsaprojeto4.py inteiro. Depois de cada mudança, me mostre
o diff. Não mexa em nada fora do escopo acima (não refatore o resto).
```

---

## Fora do escopo dessas otimizações (mas anotado)

- Chaves de API expostas em `.env` — rotacionar antes de qualquer commit
- Sem `.gitignore` — `.env`, `documentos/`, `storage/`, `cache_respostas.json`
  podem vazar
- Credenciais SQL fracas (`rm`/`rm`)
- `README.md` desatualizado (menciona LangSmith/Logfire ativos, mas o código
  desativa em `dsaprojeto4.py:32`)
- Variáveis `RAG_BACKEND` e `USAR_FAISS` no `.env` não são usadas
- Pasta `documentosvivi/` existe mas o código só lê `documentos/`
