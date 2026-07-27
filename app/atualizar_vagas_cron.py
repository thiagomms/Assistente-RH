#!/usr/bin/env python3
"""Atualiza vagas_cache.json a partir do SQL Server (Empregare), sem precisar
abrir o Streamlit. Pensado pra rodar via cron na VM, no mesmo formato de
arquivo que dsa_gerar_resposta_vagas_geral / pagina_vagas esperam ler."""

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

import pyodbc
from dotenv import load_dotenv
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_community.vectorstores import FAISS

APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR / ".env")

PASTA_STORAGE = APP_DIR / "storage"
PASTA_FAISS = PASTA_STORAGE / "faiss_index"
ARQUIVO_VAGAS_CACHE = APP_DIR / "vagas_cache.json"

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


def _conectar():
    conn_str = (
        f"DRIVER={{{os.getenv('EMPREGARE_DRIVER')}}};"
        f"SERVER={os.getenv('EMPREGARE_SERVER')};"
        f"DATABASE={os.getenv('EMPREGARE_DB')};"
        f"UID={os.getenv('EMPREGARE_USER')};"
        f"PWD={os.getenv('EMPREGARE_PASSWORD')};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=10)


def _buscar_vagas() -> list:
    conn = _conectar()
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


def _nome_amigavel(nome_arquivo: str) -> str:
    nome = Path(nome_arquivo).stem
    nome = re.sub(r"^curriculo[_-]?", "", nome, flags=re.IGNORECASE)
    nome = re.sub(r"[_-]+", " ", nome).strip()
    return nome.title() or nome_arquivo


def _melhores_matches(vagas: list, max_vagas: int = 8) -> list:
    if not PASTA_FAISS.exists():
        return []
    embed_model = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    vector_store = FAISS.load_local(str(PASTA_FAISS), embed_model, allow_dangerous_deserialization=True)
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


def main() -> int:
    vagas = _buscar_vagas()
    melhores_matches = _melhores_matches(vagas)
    ARQUIVO_VAGAS_CACHE.write_text(
        json.dumps(
            {
                "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "vagas": vagas,
                "melhores_matches": melhores_matches,
            },
            ensure_ascii=False, indent=2, default=str,
        ),
        encoding="utf-8",
    )
    print(f"OK: {len(vagas)} vaga(s) -- cache atualizado em {ARQUIVO_VAGAS_CACHE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
