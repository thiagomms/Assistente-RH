# Assistente RH

Chatbot de analise de curriculos com Inteligencia Artificial para apoiar o RH.

Em vez de ler cada curriculo manualmente, o time faz perguntas em linguagem natural — por exemplo: *"Qual candidato tem mais experiencia em logistica?"* — e o sistema responde com base nos documentos indexados.

Os curriculos de exemplo no repositorio sao **ficticios**, usados apenas para demonstracao.

## O que faz

- Interface web em Streamlit (chat)
- Indexacao local de curriculos (PDF/DOCX) com busca semantica (FAISS + FastEmbed)
- Respostas geradas via API Groq (LLM)
- Cache local de perguntas/respostas
- Atalhos Windows para abrir o app com um clique

## Tecnologias

| Tecnologia | Funcao |
|------------|--------|
| Python | Runtime da aplicacao |
| Streamlit | Interface web |
| LangChain | Orquestracao do fluxo RAG |
| FAISS + FastEmbed | Vetores e busca local nos curriculos |
| Groq API | Modelo de linguagem na nuvem |

## Estrutura do repositorio

```
AssistenteRH/
|-- app/                 # Codigo Streamlit e documentacao
|-- CRIAR_ATALHO.bat     # Cria atalho na area de trabalho
|-- criar_atalho.ps1
|-- gerenciar.ps1        # Sobe/abre o app
|-- abrir.vbs
|-- .gitignore           # Nao versiona python/, .env, caches
```

> A pasta `python/` (~1GB) e o arquivo `.env` (chaves de API) **nao** entram no Git.

## Como rodar (visao geral)

1. Ter o ambiente Python do projeto (pasta `python/` local ou ambiente proprio)
2. Configurar `.env` com a chave da Groq (e demais variaveis necessarias)
3. Usar os curriculos de demonstracao (ou adicionar os seus na pasta de documentos do app)
4. Iniciar pelo atalho / `gerenciar.ps1` ou:

```bash
cd app
streamlit run dsaprojeto4.py
```

Mais detalhes tecnicos: veja [`app/README.md`](app/README.md).

## Licenca / uso

Projeto de demonstracao e apoio ao RH.
