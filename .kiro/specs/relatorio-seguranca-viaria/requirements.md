# Requisitos — Relatório de Segurança Viária (EARS)

## R1 — Ingestão e qualidade dos dados
**User story:** Como analista, quero a base da PRF limpa e padronizada para que as métricas sejam confiáveis.
1. WHEN `ingest` é executado, THE SYSTEM SHALL baixar os CSVs anuais "agrupados por ocorrência" do Google Drive da PRF.
2. THE SYSTEM SHALL ler os arquivos com encoding latin-1 e separador `;`.
3. THE SYSTEM SHALL converter latitude/longitude e km de texto com vírgula decimal para número.
4. THE SYSTEM SHALL normalizar as grafias das causas entre os anos (acentos, caixa, sinônimos conhecidos).
5. THE SYSTEM SHALL marcar como **preliminares** os registros do ano corrente (e do ano anterior até março).
6. IF um arquivo falhar no download, THEN THE SYSTEM SHALL usar o cache local e registrar o aviso na auditoria.

## R2 — Métricas
1. THE SYSTEM SHALL definir o período atual como os 30 últimos dias com dados disponíveis (data máxima da base), não o calendário.
2. THE SYSTEM SHALL calcular a variação % de acidentes entre o período atual e os 30 dias anteriores.
3. THE SYSTEM SHALL calcular letalidade = mortos/acidentes×100 e gravidade = % de acidentes com feridos graves ou mortos.
4. THE SYSTEM SHALL ranquear as 5 principais causas e os 5 trechos mais críticos (UF+BR+km inteiro).
5. WHEN o usuário informa uma UF, THE SYSTEM SHALL filtrar todas as métricas por essa UF.
6. IF a UF for inválida, THEN THE SYSTEM SHALL rejeitar a requisição antes de qualquer chamada ao LLM.

## R3 — Gráficos
1. THE SYSTEM SHALL gerar gráfico de acidentes diários dos últimos 30 dias disponíveis.
2. THE SYSTEM SHALL gerar gráfico de acidentes mensais dos últimos 12 meses (meses completos).

## R4 — Notícias
1. THE SYSTEM SHALL buscar notícias recentes sobre acidentes, operações da PRF, feriados prolongados e obras.
2. THE SYSTEM SHALL registrar título, fonte, URL e data de cada notícia usada.
3. IF nenhuma API de notícias estiver configurada, THEN THE SYSTEM SHALL usar RSS públicos.

## R5 — Agente e explicações
1. THE SYSTEM SHALL usar um agente orquestrador que decide quais tools chamar.
2. THE SYSTEM SHALL rotular cada afirmação do texto como `[BASE PRF]` ou `[NOTÍCIA n]`.
3. THE SYSTEM SHALL NOT atribuir causa a acidente específico de notícia sem correspondência na base.
4. THE SYSTEM SHALL informar no relatório o período coberto e o caráter preliminar dos dados.

## R6 — Guardrails
1. WHEN a entrada do usuário contém pedidos fora do escopo ou injeção de prompt, THE SYSTEM SHALL recusar ou ignorar.
2. WHEN o texto do LLM cita um número que não existe nas métricas calculadas nem nas notícias citadas no parágrafo, THE SYSTEM SHALL sinalizar/remover.
3. WHEN o texto do LLM contém padrão de dado pessoal (CPF, placa, nome+idade), THE SYSTEM SHALL bloquear.
4. IF a validação falhar após N tentativas, THEN THE SYSTEM SHALL publicar o relatório só com métricas e um aviso.

## R7 — Governança e auditoria
1. THE SYSTEM SHALL gravar em JSONL cada passo: nó do grafo, tool chamada, argumentos, resumo da saída, decisão de guardrail, modelo e tempo.
2. THE SYSTEM SHALL gerar um manifesto por execução (run_id, hash dos dados, versão do prompt, fontes).
3. THE SYSTEM SHALL anexar ao relatório a seção "Transparência" com fontes e decisões.
4. THE SYSTEM SHALL gravar as notícias usadas em um snapshot por execução (hash no manifesto) e permitir reexecutar o relatório a partir dele.

## R8 — Dados sensíveis (LGPD)
1. THE SYSTEM SHALL manter allowlist explícita de campos que podem chegar ao LLM.
2. THE SYSTEM SHALL agregar dados por pessoa (idade, sexo, estado físico) em faixas e suprimir células com n < 5, aplicando supressão complementar quando um grupo tiver uma única célula suprimida.
3. THE SYSTEM SHALL NOT enviar ids, coordenadas exatas ou registros individuais ao LLM.
