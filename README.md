# decision-intelligence-core
Decision Intelligence Core
Реализация Core (Decision Intelligence Framework v1.2) по спецификации: FastAPI + gRPC, Event Sourcing через Kafka, CQRS, Merkle-anchoring с offline-верифицируемым inclusion proof.
Runtime Implementations (AI Orchestrator / Workflow / Human Review) и Domain Profiles (Banking KZ / Game / Construction) не реализованы — по заданию реализуется только Core, домен-агностично (см. <task> исходной команды).
Как это проверялось
Важно понимать, что именно доказано, а что нет:
tests/verify_core_logic_stdlib.py — выполнен реально, без единой внешней зависимости кроме stdlib и cryptography. Импортирует настоящие application/merkle.py, application/merkle_anchor_service.py и infrastructure/ed25519_signer.py (все не зависят от pydantic/fastapi) и реальные infrastructure/memory_adapters.py для идемпотентности и сквозной проверки анкоринга. 30 проверок, все прошли: формула leaf hash, построение дерева и offline-верификация (включая порчу листа), оба порога батчирования, Ed25519 sign/verify, идемпотентность по I6, I4 (INSUFFICIENT_DATA), I7 (MetricSuperseded не трогает оригинальный leaf), и (раздел 8) регрессионная проверка на баг с MerkleRootPublished, см. ниже. Запустить: make verify-core.
Все 32 .py файла прошли python -m py_compile — синтаксически корректны, включая код на pydantic/fastapi/grpc/aiokafka/redis/asyncpg, которых не было в среде, где это писалось.
tests/unit/ и tests/integration/ написаны в стиле pytest, используют реальные Pydantic-модели и полный application-слой — но не были выполнены там, где это репо собиралось: в той среде не было сети, чтобы поставить fastapi/pydantic/pytest/grpc/aiokafka/redis/asyncpg. Они написаны внимательно и вручную прослежены логически, но "все тесты проходят" из acceptance_criteria — это то, что нужно подтвердить у себя через make install-dev && make test, а не то, что уже подтверждено этим репозиторием.
docker-compose up не запускался — там же, нет ни Docker, ни сети, чтобы стянуть образы Kafka/Redis/Postgres. Файлы написаны и проверены на синтаксис/структуру (docker-compose.yml и openapi.yaml дополнительно провалидированы как YAML), но реальный подъём — на вашей стороне.
Коротко: ядро (формулы, дерево, подписи, идемпотентность, инварианты) — проверено исполнением. Обвязка (HTTP/gRPC/Kafka/Redis/Postgres/Docker) — написана по спеке, синтаксически корректна, но нуждается в вашем make install-dev && docker-compose up для финального подтверждения.
Исправленный баг: MerkleRootPublished не был виден по decision_id
Один батч почти всегда покрывает leaves из разных decision_id (это же весь смысл батчирования). Раньше MerkleAnchorService писал MerkleRootPublished только под decision_id="system", а ScoreboardProjector.rebuild(decision_id, ...) читает AuditTrail строго по одному конкретному decision_id — событие под "system" туда попасть не могло. merkle_root_ref в GetScoreboard был обречён всегда быть None, даже после закрытия батча и успешного анкоринга.
Нашлось это при разборе внешних предложенных правок — сам предложенный код не подошёл напрямую (другая сигнатура EventBus.publish, другой MerkleBatchBuilder, ProjectionStore с типизированным Scoreboard вместо dict, decision_id: UUID вместо str, используемого everywhere в этом репо включая нестрого-UUID decision_id в примерах), но сам баг — настоящий. Исправлено минимально под реальные интерфейсы: PendingLeaf теперь несёт decision_id, MerkleAnchorService._close_and_anchor() публикует MerkleRootPublished под каждым decision_id из батча (плюс по-прежнему под "system" — для батч-уровневого аудита). Никакого нового event-driven push-механизма поверх ScoreboardProjector не добавлял: rebuild() и так каждый раз честно переигрывает события с нуля, второй (push) путь обновления той же самой merkle_root_ref дублировал бы первый.
Заодно добавил merkle_timestamp в ScoreboardState (когда именно заанкорено — было предложено в тех же правках, разумное дополнение) и pattern-валидацию на leaf_hash (^[a-f0-9]{64}$).
Число "27 passed", которое было в предложенных правках — не могу подтвердить или опровергнуть, pytest тут не установлен и не запускался.
runtime_context: dict[str, str] → JsonValue
Изменено во всех слоях, не только в Python-типах:
domain/events.py (_RuntimeEvent), domain/models.py (MetricRecord), application/command_handler.py (UpdateMetricCommand) — тип теперь pydantic.JsonValue вместо dict[str, str].
grpc/core.proto — map<string, string> не может нести произвольный JSON (ни вложенность, ни не-строковые значения), поэтому runtime_context теперь google.protobuf.Struct. Без этого правка в Python была бы косметикой: gRPC-транспорт всё равно ограничивал бы Runtime Implementation плоскими строковыми парами. grpc/server.py соответственно конвертирует через json_format.MessageToDict, не dict(...).
REST-слой раньше вообще не принимал runtime_context — api/main.py хардкодил {} при построении команды. Добавил поле в api/schemas.py::UpdateMetricRequest и прокинул реальное значение. Нашлось это заодно, не было отдельным запросом.
Заодно (тот же файл, core.proto/grpc/server.py, уже открыт для правки): merkle_timestamp_unix_ms в ScoreboardState и anchor_timestamp_unix_ms в MerkleProof — поля появились в домене на прошлом шаге, но proto-контракт и gRPC-сервер не обновили тогда.
Существующие тестовые фикстуры (runtime_context={}, runtime_context={"planner": "2.3"}) менять не пришлось — dict[str, str] это валидный частный случай JsonValue, обратная совместимость сохранена автоматически.
GitHub Codespaces
.devcontainer/ уже настроен поверх существующего docker-compose.yml (не дублирует его — devcontainer.json подключает оба файла). При открытии Codespace автоматически: соберётся образ, поднимутся kafka/redis/postgres с healthcheck-гейтингом, поставятся dev-зависимости (requirements-dev.txt) и перегенерируются grpc/core_pb2.py/grpc/core_pb2_grpc.py (они не в git, регенерация после монтирования volume обязательна — иначе их не будет видно, см. комментарий в .devcontainer/docker-compose.yml).
Внутри Codespace, впервые в этом проекте реально исполнимо:
pytest -v                              # весь сьют, а не только stdlib-скрипт
docker compose up -d kafka redis postgres  # уже поднято devcontainer'ом
uvicorn api.main:app --reload          # REST на :8000
python -m grpc.server                  # gRPC на :50051
Известные пробелы (TODO в коде, не молчаливые допущения)
infrastructure/rfc3161_tsa.py::verify() — намеренно NotImplementedError. ASN.1-разбор TimeStampResp специфичен для конкретного TSA (например, НУЦ РК/КЦМР для Banking Profile KZ) и не может быть написан корректно без реального формата ответа этого TSA.
application/evidence_registry.py::all_present() — написан и корректен, но не подключён к проверке I3 в command_handler.py. Сегодня I3 проверяет только "evidence_refs не пустой", а не "каждый evidence_id реально есть в Evidence Registry" — вызывающий может сослаться на несуществующий evidence_id, и это пройдёт. Более строгая проверка требует, чтобы CommandHandler читал состояние Evidence Registry перед коммитом (через AuditTrail.read_range, не через ProjectionStore — иначе нарушится "команды не читают projection"). Не подключено сейчас сознательно: это меняет поведение _commit(), а перепроверить это исполняемым тестом в этой песочнице (нет pydantic) уже нельзя — лучше сделать отдельным, проверяемым шагом на вашей стороне, чем добавить в последний момент без возможности перезапустить verify-core по этому конкретному пути.
grpc/ как имя папки может затенять реальный пакет grpc из pip, если запускать python grpc/server.py напрямую из корня репо. Запускайте через make run-grpc (python -m grpc.server) — подробности в шапке grpc/server.py.
Domain Profiles (Banking/Game/Construction) не реализованы — Core принимает runtime_context как непрозрачные данные, ничего не значит без слоя профилей поверх.
Быстрый старт
cp .env.example .env   # при необходимости поменяйте порты/креды
make docker-up
Поднимет: Zookeeper, Kafka, Redis, Postgres, core-api (:8000), core-grpc (:50051).
Локально без Docker (использует in-memory адаптеры, CORE_ENV=local):
make install-dev
make verify-core     # быстрая проверка ядра, см. раздел выше
make test            # требует pytest — полный набор
make run-api
curl-примеры
Оценивались как "как это должно выглядеть по контракту" (openapi.yaml) — не прогонялись против живого сервера в среде без сети.

# 1. UpdateMetric — I3 требует непустой evidence_refs

curl -X POST http://localhost:8000/v1/metrics \
-H "Content-Type: application/json" \
-d '{
"decision_id": "dd-8f14e45f",
"metric_name": "kdn_limit_check",
"value": "WITHIN_LIMIT",
"idempotency_key": "dd-8f14e45f-kdn-v1",
"evidence_refs": ["ev-91a4e5f3"],
"proposed_by": "ai-orchestrator"
}'

# > 202 {"status": "ACCEPTED"}

# 2. Повторная доставка того же idempotency_key — I6

curl -X POST http://localhost:8000/v1/metrics \
-H "Content-Type: application/json" \
-d '{ ... тот же idempotency_key ... }'

# > 202 {"status": "DUPLICATE_IGNORED"}

# 3. Без evidence_refs — I3 отклоняет

curl -X POST http://localhost:8000/v1/metrics \
-H "Content-Type: application/json" \
-d '{"decision_id":"dd-2","metric_name":"aml","value":"CLEAR","idempotency_key":"k-aml-1","evidence_refs":[],"proposed_by":"critic"}'

# > 422 {"detail": "evidence_refs must be non-empty (invariant I3)"}

# 4. Прочитать состояние

curl http://localhost:8000/v1/scoreboard/dd-8f14e45f

# 5. Offline-верифицируемый Merkle proof (подождите ~5с или 1000 leaves — порог батча)

curl "http://localhost:8000/v1/merkle-proof?decision_id=dd-8f14e45f&metric_name=kdn_limit_check"
Структура проекта
Строго по project_structure из команды на реализацию: domain/ interfaces/ application/ infrastructure/ api/ grpc/ tests/.
domain/ — Pydantic-модели и события. Нет зависимостей на interfaces/infrastructure.
interfaces/ — 4 Protocol: AuditTrail, ProjectionStore, Signer, TimestampAuthority, плюс EventBus.
application/ — 8 компонентов из functional_requirements, каждый отдельным модулем: command_handler.py (Command Handler, write side, I3/I6), metrics_registry.py (Metrics Registry), evidence_registry.py (Evidence Registry), risk_matrix.py (Risk Matrix), merkle.py + merkle_anchor_service.py (Merkle Batch Builder: дерево, offline-верификация, закрытие батча, подпись, TSA-штамп), policy_evaluator.py (Policy Evaluator, I4), completion_criteria.py (Completion Criteria), scoreboard_projector.py (Scoreboard Core как read projection — агрегирует то, что реконструировали Metrics Registry/Risk Matrix, сам ничего не реконструирует напрямую).
infrastructure/ — реализации interfaces/: memory_adapters.py (для тестов), kafka_adapter.py, redis_adapter.py, postgres_audit_trail.py, ed25519_signer.py, rfc3161_tsa.py.
api/ — FastAPI (main.py), DI-сборка (deps.py), wire-схемы (schemas.py).
grpc/ — core.proto, server.py (тот же application-слой, другой транспорт).
tests/ — unit/, integration/ (pytest, полный стек) и verify_core_logic_stdlib.py (реально выполненная проверка ядра).
