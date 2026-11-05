# Assessor IA

Um assessor financeiro e de agenda feito com FastAPI, LangChain e LangGraph. Pelo chat dá para registrar gastos e receitas, corrigir lançamentos, marcar compromissos e tirar dúvidas sobre o produto. Tem também uma tela de perfil e um monitor com latência, erros, tokens e custo de cada turno.

## Como funciona

Cada mensagem passa por um guardrail de entrada e cai num roteador, que manda para o especialista certo: financeiro, agenda ou FAQ. Depois o orquestrador escreve a resposta, o guardrail de saída revisa e o juiz confere se tudo o que foi dito tem apoio no que as ferramentas devolveram.

## O que mudou na Etapa 8

Antes, as tools gravavam no banco antes de o juiz falar. Agora o turno inteiro roda numa transação do PostgreSQL e o commit só acontece depois da aprovação. Se o juiz recusar, nada fica salvo. O Google Calendar só é chamado depois do commit. Os detalhes e o porquê estão no "decisao_tecnica.md".

## Organização

- "app": API, grafo, agentes, juiz, guardrail e ferramentas.
- "app/operacoes.py": a transação do turno, que é o centro da Etapa 8.
- "frontend": chat, perfil e monitor.
- "data": o PDF que alimenta o FAQ.

## O que precisa para rodar

PostgreSQL, MongoDB e Qdrant ligados, e um ".env" na raiz com "GROQ_API_KEY", "DATABASE_URL", "MONGODB_URI", "QDRANT_URL" e "QDRANT_API_KEY". O "TYPESAFE_API_KEY" é opcional e liga o juiz JEV. Sem ele, o juiz usa a Groq. A integração com o Google Calendar também é opcional e usa as credenciais OAuth da conta.

Com a API no ar, o chat abre na raiz do servidor, o perfil em "/perfil.html", o monitor em "/monitor.html" e a documentação da API em "/docs".

Projeto com pipeline de CI/CD no GitHub Actions.
