Relatório Técnico — Assistente de RH com IA
O que é o projeto
Um chatbot de análise de currículos que usa Inteligência Artificial para responder perguntas sobre candidatos. Em vez de o RH ler cada currículo manualmente, basta digitar perguntas como "Qual candidato tem mais experiência em logística?" e o sistema responde automaticamente.

Tecnologias utilizadas
Tecnologia	Função	Onde roda
Streamlit	Interface web do chat	Servidor local (sua máquina)
Groq API	Modelo de linguagem (IA que responde)	Nuvem — EUA (servidores Groq)
FAISS	Banco de vetores dos currículos	Local — pasta storage/
FastEmbed	Converte texto em vetores numéricos	Local — sua máquina
LangSmith	Rastreamento de perguntas e respostas	Nuvem — EUA (LangChain)
LogFire	Monitoramento e logs técnicos	Nuvem — EUA (Pydantic)
Python / LangChain	Orquestração de todo o fluxo	Local — sua máquina
Onde os dados ficam armazenados

projeto-RH/
├── documentos/         ← Currículos originais (.pdf, .docx) — SOMENTE LOCAL
├── storage/
│   └── faiss_index/    ← Vetores dos currículos — SOMENTE LOCAL
├── cache_respostas.json ← Respostas salvas — SOMENTE LOCAL
└── .env                ← Chaves de API — SOMENTE LOCAL
Os currículos nunca saem da sua máquina. O que vai para a nuvem é apenas:

O texto da pergunta feita pelo usuário
O trecho relevante do currículo encontrado pelo FAISS (contexto para a IA responder)
A resposta gerada
Fluxo completo de uma pergunta

Usuário digita pergunta
        ↓
Verifica cache local (resposta já existe?)
        ↓ NÃO
FAISS busca os 5 trechos mais relevantes nos currículos (LOCAL)
        ↓
Envia para Groq: [pergunta + trechos dos currículos] → resposta
        ↓
LangSmith registra: pergunta + resposta (para auditoria)
LogFire registra: tempo de resposta + status técnico
        ↓
Resposta exibida no chat + salva no cache local
Riscos de vazamento de dados
Risco BAIXO — o que realmente sai da máquina
O que sai	Para onde	Risco
Trechos de currículo (nome, experiência, habilidades)	Groq (EUA)	Médio
Pergunta do usuário	Groq + LangSmith	Baixo
Logs técnicos (tempo, erros)	LogFire	Baixo
Pontos de atenção
Groq — empresa americana. Os dados enviados seguem a política de privacidade deles. Por padrão, a Groq não usa dados de clientes para treinar modelos, mas os dados transitam pelos servidores deles.

LangSmith — registra todas as perguntas e respostas para auditoria. Útil para controle interno, mas significa que um histórico fica armazenado na nuvem da LangChain.

Dados sensíveis nos currículos — CPF, endereço, salário pretendido presentes nos PDFs são enviados em trechos para o Groq ao responder perguntas. Isso é o principal ponto de atenção para a LGPD.

Conformidade com LGPD
Requisito LGPD	Situação atual
Dados pessoais dos candidatos	Currículos armazenados localmente ✅
Transferência internacional de dados	Ocorre para Groq e LangSmith ⚠️
Consentimento do titular	Depende do processo seletivo da empresa ⚠️
Acesso restrito	Só quem tem acesso ao servidor acessa o sistema ✅
Recomendação: informar no processo seletivo que os currículos são processados por IA, e avaliar com o jurídico se a transferência para servidores nos EUA está coberta pela política de privacidade atual da empresa.

Vantagens do modelo adotado
Velocidade: Groq é um dos LLMs mais rápidos do mercado — resposta em 1-3 segundos
Custo: plano gratuito do Groq cobre uso interno moderado (sem custo no momento)
Sem infraestrutura: não precisa de GPU nem servidor potente — roda em qualquer PC
Cache local: perguntas repetidas respondem instantaneamente sem chamar a API
Auditoria: LangSmith registra todas as interações para controle
Resumo executivo (para o chefe)
O sistema é um assistente de IA que lê os currículos enviados pelo RH e responde perguntas sobre os candidatos em segundos. Os arquivos ficam salvos somente no computador da empresa. A IA utilizada é da Groq (empresa americana, plano gratuito), e os trechos dos currículos são enviados para ela apenas no momento da pergunta. O sistema registra todas as interações para auditoria. O principal ponto jurídico a avaliar é a transferência de dados pessoais dos candidatos para servidores nos EUA, conforme a LGPD.