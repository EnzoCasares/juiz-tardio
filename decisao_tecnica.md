### 1. O que decidimos

O problema era este: a tool gravava e dava commit na hora, e o juiz só opinava depois. Com isso, o chat podia dizer “não” enquanto o banco já tinha dito “sim”.

Resolvemos com uma transação do PostgreSQL por turno. Ela abre no começo do turno, em “executar_fluxo”, e fica guardada no próprio turno. As três tools que escrevem (“add_transaction”, “update_transaction” e “add_event”) usam essa mesma conexão e não dão commit: fazem o INSERT ou o UPDATE e devolvem o resultado com status “pendente”. O destino da transação fica com o “finalizar()”, em “app/operacoes.py”, que só roda depois do veredito. Se o juiz aprovou, commit. Se recusou, não respondeu ou algo deu errado no meio, rollback.

A ordem antiga era: o modelo escolhe a tool, a tool grava e dá commit, o orquestrador escreve a frase, o juiz avalia e o chat mostra. A nova é: o modelo escolhe a tool, a tool grava sem confirmar, o orquestrador escreve, o juiz avalia, o “finalizar()” faz commit ou rollback e só então o usuário recebe a resposta.

Isso encaixou bem neste grafo porque ele já roda o turno inteiro numa chamada só. Bastou colocar o turno dentro de um contexto (“turno_operacoes”) e deixar a decisão para o final. Rota, API e os outros fluxos continuam como estavam, e não precisamos de agente novo.

A garantia vale igual para as três tools, já que todas passam por “gravar_validado”: se o turno for recusado, nenhuma linha criada ou alterada permanece em “transactions” ou em “events”.

Antes de cada escrita ainda existe um filtro, que confere se a mensagem do usuário realmente pede aquela operação, com aquele valor e aquela moeda. Pergunta, hipótese, plano futuro e negação não autorizam nada. Na prática, combinamos duas abordagens: interceptar (o filtro de intenção) e transacionar (a garantia de verdade). Só o filtro não bastaria, porque ele roda antes da escrita e não consegue desfazer nada depois.

Outro detalhe é o que o juiz lê. Em turno com escrita, o usuário não vê a frase livre do orquestrador; vê um comprovante montado com o que o banco devolveu, por exemplo “Transação confirmada: id 12, BRL -30.00”. O juiz avalia esse comprovante, comparando com a pergunta e com as linhas pendentes. Por isso o caso dos “2 dólares” deixou de acontecer: mesmo que o orquestrador escreva a moeda errada, essa frase não chega ao usuário.

### 2. O que deixamos de fora

Interceptar sozinho. Um validador julgaria a ação antes de chamar a tool. Isso tem a vantagem de que um pedido errado nem chega ao banco, mas ele decide antes de existir a resposta final e, por isso, não cobre o caso em que o juiz recusa depois. Ficou só como filtro, junto com a transação.

Adiar. A tool guardaria a operação numa lista ou numa tabela de espera, e um passo posterior aplicaria tudo depois da aprovação. O ponto a favor é não segurar conexão nem lock enquanto os modelos pensam. Contra: um “update_transaction” pode ficar velho, porque entre o pedido e a aplicação outra pessoa pode ter mudado a mesma linha, e seria preciso conferir tudo de novo. Se a fila ficasse em memória, uma queda perderia os pedidos; se ficasse numa tabela, precisaríamos de um worker e de tratamento de falha. Como a transação resolvia o problema com menos peças, não seguimos por aí.

Compensar. A tool gravaria normalmente e, na recusa, uma ação inversa apagaria ou restauraria a linha. Nada fica preso durante o julgamento, mas a linha fica visível nesse intervalo, e se o processo cair antes da compensação ela fica para sempre. No “update_transaction” ainda existe o risco de restaurar o valor antigo por cima de uma alteração feita por outra pessoa nesse meio tempo. Para a invariante da prática, era o caminho mais frágil.

### 3. Efeito no monitor da Etapa 6

Latência e p95. A transação fica aberta enquanto o orquestrador e o juiz trabalham, e o filtro de intenção acrescenta uma chamada ao modelo antes de cada escrita diferente. A latência do turno com escrita sobe, e o p95 pode chegar perto do SLO de 8 segundos. Para não travar o banco, limitamos a espera por lock a 2 segundos e cada consulta SQL a 10 segundos, só nessa transação. Não medimos o p95 com os modelos reais; esse impacto é uma estimativa pelo mecanismo, não um número medido.

Taxa de erro e status. Quando o juiz recusa, o turno termina com uma frase segura e sem exceção, então aparece como “ok” e não entra no SLO de 5%. O bloqueio do guardrail de entrada continua como “bloqueado” e também não entra. Uma exceção no commit ou no fluxo vira “erro” e conta. Juiz fora do ar também fecha como “ok”, porque a falha é tratada e o turno termina com rollback.

Tokens e custo. A chamada extra do filtro de intenção gasta tokens e custo a cada escrita. O juiz já existia, então não soma nada novo.

Comparando com adiar. Com a fila, conexão e lock só abririam depois do juiz, e o p95 sofreria menos com espera de banco. Em compensação, surgiria um segundo efeito depois do veredito: se a aplicação da fila falhasse, isso viraria “erro” num turno que o usuário já achava resolvido. Os tokens ficariam praticamente iguais, porque o filtro continuaria lá.

### 4. Outras decisões

Google Calendar. O “add_google_event” ficou fora da transação, porque o Google não participa do rollback do Postgres. Em vez disso, seguramos a chamada: durante o turno ele só anota o pedido como “pendente”, e a criação real acontece depois da aprovação e do commit local. Se o turno for recusado, nada vai para o Google. Se o Google falhar depois do commit, o evento local continua salvo e a resposta pede para o usuário conferir o calendário antes de tentar de novo.

Histórico no Mongo. O “salvar_mensagem” também fica fora da transação. A mensagem do usuário é salva na entrada; a resposta só é salva depois do veredito, já com a frase que o usuário viu. Se o Mongo falhar depois de um commit, não tratamos isso como erro, para o usuário não repetir o pedido e gravar duas vezes. A resposta só recebe um aviso.

Juiz sem resposta. Se o JEV falhar, o juiz tenta pela Groq. Se a Groq também falhar, o turno faz rollback e o usuário lê que nada foi registrado porque a validação está indisponível. Na dúvida, nada é confirmado.

Queda no meio. Se o processo cair antes do commit, o Postgres desfaz a transação sozinho quando a conexão some. Se cair depois, a escrita permanece, mas pode faltar o Google ou o histórico. O único ponto realmente incerto é quando o commit acontece e a confirmação se perde na rede.

Pedido repetido. No mesmo turno, chamadas iguais são deduplicadas e a escrita acontece uma vez só. Entre turnos não há chave de idempotência, então um pedido aprovado e repetido depois grava de novo. Depois de uma recusa, repetir não causa problema, porque nada ficou. Também ajustamos a memória da conversa: antes ela guardava “Registrei seu gasto” até na recusa, e agora guarda a frase segura que o usuário de fato leu.

Evidência. Os testes rodaram num PostgreSQL isolado de verdade, com o juiz simulado para forçar recusa ou aprovação. Cada tentativa usou um marcador único, e registramos o estado antes e depois.

“add_transaction”, recusa. Marcador ETAPA8-31c900f8-f348-46d7-8b3a-22ac2bc7bd96. Antes 0 linhas, rótulo [juiz] sem_apoio, depois 0 linhas.
“add_transaction”, aprovação. Marcador ETAPA8-c7f58fdb-e4e5-4800-a3b5-80adeb8b556f. Antes 0 linhas, rótulo [juiz] apoiada, depois 1 linha.
“update_transaction”, recusa. Marcador ETAPA8-0b56e8f3-df3f-48a1-a2f5-3f0b942dca93. Antes -20.00, rótulo [juiz] sem_apoio, depois -20.00.
“update_transaction”, aprovação. Marcador ETAPA8-3e322256-50af-46c0-b9ab-c1e2a9ed99d3. Antes -20.00, rótulo [juiz] apoiada, depois -30.00.
“add_event”, recusa. Marcador ETAPA8-5476d42d-ddf1-414a-8300-6b9264a4d642. Antes 0 linhas, rótulo [juiz] sem_apoio, depois 0 linhas.
“add_event”, aprovação. Marcador ETAPA8-960a94f8-58f5-40fa-b561-b65152aede9d. Antes 0 linhas, rótulo [juiz] apoiada, depois 1 linha.

Nenhuma linha foi apagada na mão entre os testes. Passaram também os casos de juiz indisponível, exceção depois da tool, pedido duplicado no mesmo turno, Google com falha e as três escritas pela entrada MCP, que segue o mesmo caminho; ao todo, 98 testes. Com o JEV real, o juiz aprovou uma resposta apoiada e recusou uma afirmação sem evidência. Não conseguimos comprovar o fluxo completo pelo chat com a Groq real, que respondeu 403 na rodada de teste, nem o Google real, por falta do token OAuth.

### 5. Arquivos criados e modificados

Criados:

“app/operacoes.py”: a transação do turno, o filtro de intenção e o “finalizar()”.
“decisao_tecnica.md”: este documento.

Modificados:

“app/graph.py”: abre a transação no início do turno, chama o “finalizar()” depois do juiz e monta o comprovante só depois do commit.
“app/juiz.py”: ganhou o “autorizar_operacao” e passou a avaliar o comprovante do banco nos turnos com escrita.
“app/tools/financeiro.py”: “add_transaction” e “update_transaction” deixaram de dar commit e passaram a usar a conexão do turno.
“app/tools/agenda.py”: “add_event” deixou de dar commit e passou a usar a conexão do turno.
“app/tools/calendario_google.py”: o “add_google_event” agora só anota o pedido, e a criação acontece depois do commit.
“app/prompts.py”: os agentes sabem que “pendente” ainda depende do juiz e não devem repetir a operação.
“README.md”: atualizado para a Etapa 8.
