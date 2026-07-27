# Assistente RH

Chatbot de an�lise de curr�culos com Intelig�ncia Artificial para apoiar o RH.

Em vez de ler cada curr�culo manualmente, o time faz perguntas em linguagem natural � por exemplo: *"Qual candidato tem mais experi�ncia em log�stica?"* � e o sistema responde com base nos documentos indexados.

Os curr�culos de exemplo no reposit�rio s�o **fict�cios**, usados apenas para demonstra��o.

## O que faz

- Interface web em Streamlit (chat)
- Indexa��o local de curr�culos (PDF/DOCX) com busca sem�ntica (FAISS + FastEmbed)
- Respostas geradas via API Groq (LLM)
- Cache local de perguntas/respostas
- Atalhos Windows para abrir o app com um clique

## Tecnologias

| Tecnologia | Fun��o |
|------------|--------|
| Python | Runtime da aplica��o |
| Streamlit | Interface web |
| LangChain | Orquestra��o do fluxo RAG |
| FAISS + FastEmbed | Vetores e busca local nos curr�culos |
| Groq API | Modelo de linguagem na nuvem |

## Estrutura do reposit�rio

```
AssistenteRH/
??? app/                 # C�digo Streamlit e documenta��o
??? CRIAR_ATALHO.bat     # Cria atalho na �rea de trabalho
??? criar_atalho.ps1
??? gerenciar.ps1        # Sobe/abre o app
??? abrir.vbs
??? .gitignore           # N�o versiona python/, .env, caches
```

> A pasta `python/` (~1GB) e o arquivo `.env` (chaves de API) **n�o** entram no Git.

## Como rodar (vis�o geral)

1. Ter o ambiente Python do projeto (pasta `python/` local ou ambiente pr�prio)
2. Configurar `.env` com a chave da Groq (e demais vari�veis necess�rias)
3. Usar os curr�culos de demonstra��o (ou adicionar os seus na pasta de documentos do app)
4. Iniciar pelo atalho / `gerenciar.ps1` ou:

```bash
cd app
streamlit run dsaprojeto4.py
```

Mais detalhes t�cnicos: veja [`app/README.md`](app/README.md).

## Licen�a / uso

Projeto de demonstra��o e apoio ao RH.
