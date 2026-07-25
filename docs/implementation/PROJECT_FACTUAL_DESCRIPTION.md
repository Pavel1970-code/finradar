# FinRadar: фактическое состояние реализации

Дата проверки: 2026-07-19  
Проверенный commit: `fec212c` (`feat: Implement bank synchronization history and connectors`)  
Объект проверки: код, миграции, тесты, документация и локальная база данных в текущем рабочем дереве.

## 1. Значение статусов

В документе используются только четыре статуса.

| Статус | Критерий |
| --- | --- |
| **Implemented and tested** | Функция реализована в коде и покрыта выполняемыми автоматическими тестами в текущем окружении. Это не означает эксплуатационную сертификацию на Windows или проверку с реальной внешней системой, если такая проверка отдельно не указана. |
| **Implemented but not fully tested** | Рабочий код существует, но отсутствует существенная проверка целевой среды, полного запуска или эксплуатационного сценария. |
| **Partially implemented** | Реализованы интерфейсы или отдельные участки цепочки, но сквозная функция для пользователя не завершена. |
| **Planned** | Рабочего кода функции нет. Могут существовать архитектурное решение, описание или место расширения. |

## 2. Краткий вывод

Текущий проект является локальным прототипом расчётного ядра и интеграционной архитектуры. Он уже может прочитать данные из собственной SQLite-базы или тестового коннектора, проверить их полноту, построить 30-дневный денежный прогноз, определить дату первого отрицательного остатка и сохранить входной снимок и результат анализа.

Проект пока не является действующей моделью на реальных данных: нет транспорта
к реальной 1С, автоматического банковского API, загрузчика официальных
документов, AI/RAG-компонента и проверенной Windows-сборки. Реальные нормы
Грузии вручную зафиксированы только для узкого НДС и стандартной зарплаты;
бухгалтерские данные в этих сценариях вымышлены, а специальные налоговые случаи
не реализованы.

## 3. Сводная матрица функций

### 3.1. Десктопное приложение и запуск

| Функция | Статус | Фактическое состояние |
| --- | --- | --- |
| Окно прогноза на PySide6 | **Implemented and tested** | Отображает предварительный отчёт, текущий и прогнозный остаток, минимальный баланс, дату первого кассового разрыва и требуемое финансирование. Есть два offscreen UI-теста. |
| Показ ограничений и блокирующих ошибок в окне | **Implemented and tested** | При `limited` прогноз показывается вместе с предупреждениями; при `blocked` финансовые показатели скрываются. |
| Полный старт приложения | **Implemented but not fully tested** | При запуске выполняются миграции, retention архива, чтение активных правил, синхронизация с прототипной БД, проверка готовности, расчёт и запись истории. Полный процесс с реальным GUI не проверялся как собранное приложение. |
| Кнопка «Дать прогноз» | **Planned** | Кнопки нет. Сейчас расчёт выполняется один раз до открытия окна. |
| Повторная синхронизация без перезапуска | **Planned** | Нет команды обновления, фонового цикла или кнопки повторного расчёта. |
| Пользовательская настройка источника, 1С, банка и горизонта | **Planned** | В UI нет мастера подключения или экрана настроек. Горизонт в `main.py` зафиксирован на 30 днях. |
| Пользовательское представление налоговых обязательств, штрафов и stress-сценария | **Partially implemented** | Данные рассчитываются в прикладном слое, но текущее окно показывает только основной денежный прогноз и не выводит подробности фискального анализа. |
| Обработка ошибок запуска для обычного пользователя | **Partially implemented** | Доменные проверки и исключения существуют, но отдельного пользовательского экрана для ошибок миграции, подключения или повреждения истории нет. |

### 3.2. Бухгалтерские данные и 1С

| Функция | Статус | Фактическое состояние |
| --- | --- | --- |
| Канонический снимок бухгалтерских данных | **Implemented and tested** | `FinancialSnapshot` содержит профиль компании, остатки, бухгалтерские метрики, фактические и плановые события, ошибки источника, курсор и ссылки на интеграционные запуски. Текущая схема JSON — v3; чтение v1–v3 проверено. |
| Контракт read-only бухгалтерского коннектора | **Implemented and tested** | Определены capabilities, проверка соединения, full/incremental request и выдача снимка. SDK отклоняет writable-коннекторы и несогласованные данные. |
| Проверка данных от коннектора | **Implemented and tested** | Проверяются declared datasets, source identity, timezone, уникальность ID, конечность и неотрицательность сумм, формат курсора и согласованность объявленных/фактических наборов. |
| Коннектор к текущей прототипной SQLite-базе | **Implemented and tested** | Read-only преобразует `companies`, `cash_accounts`, `cash_flow_items` в канонический снимок. Не выдаёт бухгалтерские метрики, jurisdiction и tax regime. |
| Детерминированный demo-коннектор | **Implemented and tested** | Формирует полностью вымышленные данные для тестов, включая метрику `fictional_taxable_revenue`. |
| Адаптер и mapping profile для 1С | **Partially implemented** | Реализовано преобразование сырых записей компании, остатков, фактов, метрик, платёжного календаря и канонических зарплатных строк; ошибки отдельных записей превращаются в source issues. Проверено только с fixture-транспортом. |
| Канонический локальный зарплатный набор | **Implemented and tested** | Snapshot v5 хранит отдельные базы налога и пенсии, чистую зарплату, удержания, расход работодателя, пенсионный статус и сроки без имени/личного номера работника. Реальное соответствие регистрам конкретной 1С не проверялось. |
| Стандартные зарплатные нормы Грузии | **Implemented and tested** | Версионированный снимок содержит 20% подоходного налога, пенсионные доли 2% + 2%, государственные пороги и основные сроки по публикациям 245 и 12. Льготы и специальные случаи не реализованы. |
| Версионированный каталог налоговых ставок Грузии | **Implemented and tested** | Локальный SHA-256-protected JSON содержит 16 правил, их базы, условия, обязательные fact IDs, статьи и операционные периоды. Все шесть налогов представлены; неперенесённые таблицы акциза, импорта и земли помечены `reference_only`. Каталог не является общим исполняемым налоговым движком. |
| Реальный транспорт к 1С | **Planned** | Нет COM, файлового обмена, named pipe, OData/HTTP или локального sidecar. Не выбрана конкретная конфигурация 1С и её схема. |
| Автоматическая первая полная ревизия 1С | **Planned** | Контракт допускает полный снимок, но оркестрация реального первого импорта отсутствует. |
| Автоматические последующие incremental-обновления | **Partially implemented** | В контракте есть `since`, `cursor`, `next_cursor` и capability flag. Приложение не загружает предыдущий курсор и не планирует последующий запуск. |
| Обновление основных таблиц из внешней бухгалтерии | **Planned** | Снимок сохраняется в append-only истории, но `companies`, `cash_accounts` и `cash_flow_items` из внешнего коннектора не обновляются. Текущий прототипный коннектор, наоборот, читает эти таблицы. |

### 3.3. Банковские операции

| Функция | Статус | Фактическое состояние |
| --- | --- | --- |
| Канонические модели банковской выписки | **Implemented and tested** | Есть batch, statement и transaction с provider ID, счётом, датами booking/value, направлением, статусом, суммой, валютой, контрагентом и происхождением. |
| Контракт read-only банковского коннектора | **Implemented and tested** | Определены capabilities, full/incremental request и SDK-проверки источника, ID, timestamp и курсора. |
| Импорт локальной CSV-выписки | **Implemented and tested** | Ограничение 20 MiB, mapping колонок, кодировка/разделитель, отклонение symlink, диагностика строк, дедупликация и детерминированный derived ID при отсутствии provider ID. |
| Сопоставление банка с бухгалтерией | **Implemented and tested** | Сначала используется явный transaction ID, затем уникальное точное совпадение по дате, направлению, сумме, валюте и счёту. Неоднозначность не разрешается догадкой. |
| Выявление пропущенных банковских операций и устаревшего покрытия | **Implemented and tested** | Формируются issues для `missing_in_accounting`, ambiguous, conflict, stale coverage, несходящегося closing balance и расхождения банка с бухгалтерским остатком. |
| Локальная история банковских синхронизаций | **Implemented and tested** | Batch сохраняется как canonical JSON с SHA-256; запись и снимок защищены SQLite-триггерами от update/delete. |
| Использование CSV-банка в текущем desktop startup | **Partially implemented** | Сервис умеет принять bank connector и recorder, но `main.py` их не передаёт; UI не позволяет выбрать файл. |
| MT940, CAMT.053, XLSX и форматы конкретных банков | **Planned** | Реализован только CSV. |
| Автоматическое получение операций через банковский API | **Planned** | Нет API-клиента, OAuth/ключей и отдельной сетевой границы для конфиденциальных банковских данных. Текущая архитектура разрешает интернет только Regulatory Monitor, поэтому банковский API требует отдельного решения безопасности. |

### 3.4. Детерминированные расчёты

| Функция | Статус | Фактическое состояние |
| --- | --- | --- |
| Ежедневный денежный прогноз | **Implemented and tested** | Для каждого дня: `closing = previous closing + inflow - outflow`; суммы округляются до 0.01 методом `ROUND_HALF_UP`. События вне горизонта игнорируются. |
| Определение кассового разрыва | **Implemented and tested** | Возвращаются первый день отрицательного closing balance, минимальный баланс и `required_funding = max(0, -minimum_balance)`. |
| Консолидация нескольких счетов одной валюты | **Implemented but not fully tested** | Код суммирует все переданные остатки и блокирует другую валюту, но отдельных автоматических сценариев с несколькими счетами и несовместимыми валютами нет. Конвертации и курса нет. |
| Применимость фискального правила | **Implemented and tested** | Проверяются active status, период действия, jurisdiction, tax regime и наличие профиля. Результат: `applied`, `not_applicable` или `unresolved`. |
| Процентное налоговое обязательство | **Implemented and tested** | Формула: последняя подходящая named metric × rate; дата платежа = конец периода + заданное число дней. Реализован только этот общий тип правила. |
| Сопоставление рассчитанного обязательства с календарём | **Implemented and tested** | Stable obligation key предотвращает повторное добавление; учитываются отменённые, оплаченные и частично оплаченные записи. |
| Пеня за просрочку | **Implemented and tested** | Расчёт по дням с grace period и периодами ставок. Пробел, пересечение или отрицательная ставка делает результат `unresolved`, а не частичным. |
| Штраф | **Implemented and tested** | Поддерживается либо фиксированная сумма, либо процент остатка, optional min/max и требование решения органа. Неполная формула даёт `unresolved`. |
| Основной и стрессовый прогнозы | **Implemented and tested** | Accrued/calculated последствия входят в основной прогноз; contingent — в stress forecast. |
| Исключение повторно начисленных последствий | **Implemented and tested** | Начисление, уже пришедшее из бухгалтерии со связью с обязательством, распознаётся как `accrued`; совпадающее рассчитанное/условное начисление не должно дублироваться. |
| Реальные налоговые расчёты Грузии | **Partially implemented** | Узкие стандартные расчёты НДС и зарплатного налога реализованы и проверены на вымышленных данных. Отдельный каталог содержит проверенные текущие ставки, но остальные правила ещё не сопоставляются автоматически с бухгалтерскими фактами и не активированы в общем fiscal pipeline. |
| Льготы, возврат налогов и новые типы налогов | **Planned** | Формат regulatory package допускает candidate types `tax_benefit`, `tax_refund` и `tax_obligation`, но расчётных классов и формул для льгот/возвратов нет. |
| Сравнение «было — стало — прогноз» | **Partially implemented** | Версии и supersession правил сохраняются, а результаты анализа — append-only. Отдельного алгоритма, который рассчитывает два набора правил и показывает delta, нет. |
| Валютная конвертация и курсы НБГ | **Planned** | `exchange_rate` допустим как тип кандидата в публичном пакете, но нет модели курса, загрузки и применения в Core. |

### 3.5. Недостающие и сомнительные данные

| Функция | Статус | Фактическое состояние |
| --- | --- | --- |
| Итоговая готовность `ready / limited / blocked` | **Implemented and tested** | Любая ошибка даёт `blocked`; только warnings — `limited`; отсутствие issues — `ready`. При `blocked` прогноз не запускается. |
| Проверка профиля и остатков | **Implemented and tested** | Выявляются отсутствующий профиль, unavailable/empty balances, баланс старше допустимого возраста и несовместимая валюта. По умолчанию возраст баланса — не более одного дня. |
| Проверка платёжного календаря и бухгалтерских фактов | **Implemented and tested** | Их отсутствие даёт warnings о возможной неполноте будущих платежей или фискального анализа. Пустой, но объявленный доступным календарь не считается ошибкой. |
| Проверка jurisdiction и tax regime | **Implemented and tested** | Отсутствие выдаётся как warning и отдельно приводит к `unresolved` для правила, которому эти поля нужны. |
| Ошибки mapping 1С/CSV | **Implemented and tested** | Плохая запись исключается, а пользователю передаётся issue с влиянием на прогноз. В реальном источнике это ещё не проверялось. |
| Проверка недавних банковских данных | **Implemented and tested** | Может сообщить, сколько последних дней не покрывает выписка, и сколько операций отсутствует в бухгалтерии. |
| Точная диагностика вида «бухгалтер не внесла расходы» | **Partially implemented** | Такая формулировка появляется только при наличии банковской операции без бухгалтерского соответствия. Без независимого банковского источника система не может доказать пропуск. |
| Общая проверка полноты первичных документов и бизнес-аномалий | **Planned** | Нет проверки непрерывности нумерации документов, обычной периодичности расходов, просроченной дебиторки, зарплатного календаря или статистических аномалий. |

### 3.6. Налоговые правила и Regulatory Monitor

| Функция | Статус | Фактическое состояние |
| --- | --- | --- |
| Отдельный процесс `finradar-monitor` | **Implemented and tested** | Это отдельный Python distribution и entry point со своей БД, каталогом ключей и outbox. Он не импортирует Core. |
| Хранилище публичных документов | **Implemented and tested** | SQLite-таблица хранит URL, document ID, даты, язык, content и SHA-256. В ней не предусмотрены данные компании. |
| Allowlist официальных источников | **Implemented and tested** | Разрешены только HTTPS/443 hostnames Matsne, Revenue Service, Ministry of Finance и National Bank. Проверяются deceptive hostnames, credentials и порт. |
| Скачивание документов из официальных источников | **Planned** | Downloader отсутствует. Текущий `finradar-monitor` только инициализирует БД или ключ и выводит число документов. |
| Извлечение дат, ставок, штрафов, пеней и других фактов | **Planned** | Нет parser, structured-source adapter, OCR, RAG или AI extraction pipeline. |
| Контракт публичного regulatory package v2 | **Implemented and tested** | Строгий JSON, exact fields, лимит 5 MiB, до 100 sources и 1000 candidates, SHA-256, expiry, evidence и рекурсивный запрет финансовых/секретных полей. |
| Подписание пакета Ed25519 | **Implemented and tested** | Monitor может создать ключ, подписать canonical package и атомарно записать его в outbox. |
| Core-проверка входящего пакета | **Implemented and tested** | Проверяются структура, allowlist, размер, время, доверенный/неотозванный ключ, подпись, replay и архивный hash; ошибки уходят в quarantine с audit record. |
| Initial trust и rotation ключей | **Implemented and tested** | Есть одноразовый bootstrap публичного ключа, idempotency только для того же ключа, подписанная rotation и revocation с append-only историей. |
| Retention отклонённых пакетов | **Implemented and tested** | По умолчанию quarantine bytes — 30 дней, replay bytes — 7 дней. Удаление проверяет путь и hash и пишет append-only событие; accepted bytes не удаляются этим механизмом. |
| Автоматический перенос файла из Monitor outbox в Core inbox | **Planned** | Нет file watcher, scheduled importer или UI-команды импорта. |
| Преобразование принятого candidate в `FiscalRuleVersion` | **Planned** | Importer возвращает проверенный package, но не вызывает fiscal rule registry и не преобразует `rule_data` в расчётные классы. |
| Жизненный цикл правил | **Implemented and tested** | `candidate -> validated -> reviewed -> active -> superseded`; прямые переходы запрещены, при активации новой версии старая active-версия superseded. |
| Экран юридической проверки и активации | **Planned** | API registry существует, пользовательского workflow нет. |
| Полностью автоматическое обновление налоговой базы | **Planned** | Сквозная цепочка download → extraction → signed package → import → review → active rule отсутствует. Автоматическая активация по архитектуре не предполагается. |
| AI-перевод документов и результатов на обычный язык | **Planned** | В dependencies и коде нет OpenAI, локальной LLM, embeddings, vector database или prompt pipeline. |

### 3.7. Хранение, аудит и безопасность

| Функция | Статус | Фактическое состояние |
| --- | --- | --- |
| Миграции локальной БД | **Implemented and tested** | Семь Alembic revisions создают 17 прикладных таблиц; вместе со служебной `alembic_version` в текущей БД 18 таблиц. Проверены новая БД и baseline существующей прототипной БД без потери исходных данных. |
| История бухгалтерских снимков | **Implemented and tested** | Каждый запуск может сохранить полный canonical JSON и SHA-256. Снимок нельзя update/delete через SQLite triggers. |
| История фискального анализа | **Implemented and tested** | Хранит входной synchronization run ID, дату, горизонт, algorithm version `fiscal-v1`, основной/stress forecast, применимость, reconciliation и последствия. |
| Проверка целостности истории при чтении | **Implemented and tested** | Для бухгалтерского, банковского и фискального JSON пересчитывается SHA-256. |
| Ротация/очистка финансовой истории | **Planned** | Retention есть только для отклонённых regulatory package bytes. Финансовые snapshots и analysis runs растут без автоматического удаления или сжатия. |
| Шифрование локальной БД | **Planned** | SQLite-файл хранится без encryption at rest. Это блокирующее ограничение перед реальными финансовыми данными. |
| Резервное копирование и восстановление | **Planned** | Нет встроенного backup/restore и проверки восстановления. |
| Разграничение нескольких пользователей | **Planned** | Текущий runtime использует SQLite одного пользователя. Серверная on-premise БД только описана как будущий вариант. |

### 3.8. Windows и физическая граница

| Функция | Статус | Фактическое состояние |
| --- | --- | --- |
| Три независимых Python distributions | **Implemented and tested** | `finradar`, `finradar-contracts`, `finradar-monitor`; тесты проверяют направления импортов и wheel policy. |
| Запрет сетевых клиентов в Core source/dependencies | **Implemented and tested** | AST и dependency tests запрещают известные HTTP/cloud/telemetry клиенты и Qt network modules. Это статическая проверка известного списка, а не доказательство отсутствия любого сетевого вызова. |
| PyInstaller specs для Core и Monitor | **Implemented but not fully tested** | Specs раздельны, Core включает Alembic resources, build-time helper проверяет запрещённые modules/binaries. PyInstaller отсутствует в текущем macOS venv; Windows artifacts здесь не собирались. |
| Готовый Windows executable | **Planned** | В репозитории нет проверенного `.exe` или опубликованного Windows artifact. |
| Windows installer и code signing | **Planned** | Installer не создан; подпись executable/installer не выполняется. |
| ACL-разделение Core, Monitor и exchange | **Implemented but not fully tested** | PowerShell создаёт разные principals/ACL и one-way exchange. Автотесты только проверяют наличие ключевых конструкций в тексте; реальное выполнение на Windows не проводилось. |
| Firewall boundary | **Implemented but not fully tested** | Скрипт блокирует Core public Internet, Monitor local/intranet, inbound, UDP и non-HTTPS; allowlist остаётся в приложении. Политика не проверена на целевой Windows VM. |
| S4U scheduled task Monitor | **Implemented but not fully tested** | Скрипт создаёт restricted local user и задачу при старте и каждые 6 часов. Сам Monitor пока не выполняет download cycle, поэтому расписание запускает только инициализацию/подсчёт документов. |
| Cross-identity acceptance scripts | **Implemented but not fully tested** | Есть реальные filesystem probes от имени Core и Monitor, но они не выполнялись в этом окружении и не подтверждены на release VM. |
| Физически подтверждённая изоляция | **Partially implemented** | Разделение packages и deployment scripts существует; до Windows acceptance, подписанного installer и executable network tests граница не считается эксплуатационно доказанной. |
| Защита private key через DPAPI/CNG/HSM | **Planned** | Сейчас POSIX permissions или проектируемый Windows ACL; аппаратная/OS key custody не реализована. |

## 4. Архитектура и потоки данных

### 4.1. Исполняемые контуры

1. **Core (`finradar`)** — локальное desktop-приложение, доменные расчёты, SQLite, UI, история и inbound regulatory validation. В Core нет реализованного интернет-клиента.
2. **Contracts (`finradar-contracts`)** — нейтральная библиотека форматов regulatory package, trust/rotation records, source policy и Ed25519. Не содержит UI, бухгалтерских моделей или downloader.
3. **Regulatory Monitor (`finradar-monitor`)** — отдельный процесс для публичных документов, signing keys и outbox. Сейчас сетевой код отсутствует.

Фактическая и планируемая связность:

```text
текущая SQLite-база ───────────────┐
demo connector ────────────────────┼─> FinancialSnapshot v3
реальная 1С ── [нет транспорта] ───┘          │
                                              ├─> SDK validation
локальный CSV банка ─> BankBatch ─> reconcile ┤
bank API ── [нет реализации] ─────────────────┘
                                              │
                                              ├─> readiness report
active fiscal rules из Core SQLite ───────────┼─> deterministic analysis
                                              ├─> audit histories
                                              └─> desktop window

официальные сайты ── [нет downloader] ─> Monitor public DB
                                           │
                              [нет extraction/RAG/AI]
                                           │
                                  signed package v2
                                           │
                               one-way exchange directory
                                           │
                                  Core verify/quarantine
                                           │
                  [нет mapping candidate -> fiscal registry]
                                           │
                              review/activation [нет UI]
```

### 4.2. Инвентарь программных модулей

| Package / module | Назначение | Использование сейчас |
| --- | --- | --- |
| `finradar.domain.forecast` | Чистая функция ежедневного cash forecast и денежное округление | Используется единым аналитическим pipeline и тестами |
| `finradar.domain.financial_snapshot` | Канонические бухгалтерские данные и provenance | Основной входной контракт Core |
| `finradar.domain.data_readiness` | Issues и итог `ready/limited/blocked` | Вызывается перед каждым прогнозом через synchronization service |
| `finradar.domain.fiscal` | Применимость, процентное обязательство и reconciliation | Используется только при наличии active rules |
| `finradar.domain.fiscal_consequences` | Пени, штрафы, violation events и consequence states | Используется только при наличии соответствующих active rules/events |
| `finradar.domain.banking` | Bank batch, statement и transaction | Используется CSV/fixture connectors и reconciliation |
| `finradar.application.accounting_connector` | Protocol и request бухгалтерских адаптеров | Используется всеми accounting connectors |
| `finradar.application.bank_connector` | Protocol и request банковских адаптеров | Сервис поддерживает; `main.py` не подключает |
| `finradar.application.integration_sdk` | Проверка результатов адаптеров до анализа | Вызывается synchronization service |
| `finradar.application.synchronization_service` | Оркестрация accounting → optional bank → readiness → analysis → audit | Основной прикладной pipeline текущего Core |
| `finradar.application.analytical_service` | Объединение cash events, obligations, penalties/fines и scenarios | Основной расчётный pipeline |
| `finradar.application.forecast_service` | Прямой простой прогноз из старых Core tables | Существует, но текущий `main.py` его не использует |
| `finradar.application.*_history` | Protocols записи истории | Реализованы SQLAlchemy adapters |
| `finradar.infrastructure.connectors.demo` | Вымышленный reference source | Тесты |
| `finradar.infrastructure.connectors.prototype_database` | Read-only mapping текущей Core DB | Текущий desktop startup |
| `finradar.infrastructure.connectors.one_c` | 1C mapping shell и fixture transport | Тесты; реального транспорта нет |
| `finradar.infrastructure.connectors.bank` | Fixture и CSV bank adapters | Тесты/API; desktop startup не подключён |
| `finradar.infrastructure.fiscal_rule_registry` | Immutable definitions и lifecycle | Active rules загружаются при старте; registry UI/CLI нет |
| `finradar.infrastructure.regulatory_inbox` | Verify, accept/quarantine, replay protection и archive | Программный API; startup/outbox polling не подключены |
| `finradar.infrastructure.regulatory_trust_store` | Public-key bootstrap, rotation и revocation | Bootstrap доступен CLI; дальнейший operator workflow не подключён |
| `finradar.infrastructure.regulatory_retention` | Удаление старых rejected raw packages | Автоматически при старте Core |
| `finradar.ui.main_window` | Readiness и cash forecast presentation | Текущее desktop window |
| `finradar_contracts.regulatory_package` | Строгая package schema v2 | Monitor export и Core import |
| `finradar_contracts.signatures` | Ed25519 primitives | Package/trust signatures |
| `finradar_contracts.source_policy` | Exact official-host allowlist | Package validation; downloader пока отсутствует |
| `finradar_contracts.trust_records` | Initial trust и rotation record schemas | Monitor/Core trust operations |
| `finradar_monitor.storage` | Public-document SQLite | Программная запись; автоматического наполнения нет |
| `finradar_monitor.signing_keys` | Monitor private-key file store | Bootstrap/export и package signing |
| `finradar_monitor.package_export` | Atomic signed JSON export | Программный API; main cycle не вызывает |
| `finradar_monitor.main` | Инициализация paths, DB и signing key | Entry point; download/extraction cycle отсутствует |

### 4.3. Направление финансовых данных

Бухгалтерские и банковские данные поступают только в Core. Regulatory Monitor не имеет API Core и формат пакета рекурсивно отклоняет известные финансовые и секретные поля. Обратного потока Core → Monitor в коде нет.

Это архитектурная и статически тестируемая граница. На macOS она не является физической изоляцией процессов по OS identities. Для Windows такая изоляция описана PowerShell-скриптами, но пока не подтверждена выполнением.

## 5. Откуда сейчас поступают данные

| Источник | Что реально поступает | Использование текущим `main.py` |
| --- | --- | --- |
| `data/finradar.db` | Одна прототипная компания, один счёт, восемь cash-flow records | Да, через `PrototypeDatabaseConnector` |
| `DemoAccountingConnector` | Вымышленный профиль, остаток, метрика и два плановых события | Только тесты и reference-сценарии |
| `FixtureOneCTransport` | Заданный тестом raw extract | Только тесты |
| Локальный CSV банка | Транзакции одного statement по configurable mapping | Код и тесты есть; desktop startup не подключён |
| Fixture bank connector | Заданный тестом bank batch | Только тесты |
| Monitor public storage | Документы, записанные программным вызовом | Downloader не пишет их автоматически |
| Официальные сайты Грузии | Ничего | Сетевой клиент отсутствует |
| Реальная 1С | Ничего | Транспорт отсутствует |
| Банковский API | Ничего | Клиент отсутствует |
| AI/RAG | Ничего | Компонент отсутствует |

Текущий локальный development database имеет revision `0007_integration_sdk`, 17 прикладных таблиц плюс служебную `alembic_version` (18 всего), 2 бухгалтерских synchronization runs, 1 fiscal analysis run, 0 fiscal rule versions, 0 regulatory imports и 0 bank synchronization runs. Файл занимает 327,680 bytes. Это состояние локальной рабочей базы, а не характеристика поставляемого продукта.

## 6. Как обновляется налоговая база

Термин «налоговая база» в проекте относится к двум разным наборам данных.

### 6.1. Бухгалтерская база для расчёта

`AccountingMetric` содержит code, amount, currency и период. Для процентного правила берётся последняя метрика с требуемым code, период которой завершён не позже даты анализа. Эта метрика должна заново прийти в текущем `FinancialSnapshot`.

Сейчас реальная метрика из 1С не поступает. Прототипная SQLite-схема также не содержит accounting metrics, поэтому desktop startup не может рассчитать налог по этой схеме. Метрика есть только в demo-коннекторе для тестов.

### 6.2. База фискальных правил

Определения правил хранятся локально как immutable versioned JSON. В расчёт попадают только версии со статусом `active`. Старая active-версия автоматически переводится в `superseded` при активации новой reviewed-версии того же `rule_id`.

Отдельно поставляется immutable baseline `georgia_tax_rates_v1.json`. Он
содержит проверенные нормативные значения и требования к фактам, но не
регистрируется автоматически как `active` и не применяет себя к бухгалтерским
данным. Это разделяет наличие нормативного числа и готовность исполняемой
формулы.

На текущем этапе обновление возможно только программным вызовом registry API: зарегистрировать candidate и последовательно провести его через validation, review и activation. Нет CLI/UI для этой операции и нет автоматической связи с принятым regulatory package.

Следовательно, налоговая база **не обновляется автоматически из интернета**. Проект содержит защищённые строительные блоки доставки кандидатов, но не завершённую систему обновления правил.

## 7. Что выполняется полностью автоматически сейчас

При обычном запуске Core без специальных CLI-аргументов автоматически выполняются:

1. создание data directory;
2. upgrade SQLite schema до Alembic head;
3. retention raw bytes старых quarantined/replayed regulatory packages;
4. загрузка active fiscal rules из Core DB;
5. чтение текущей прототипной SQLite-схемы через read-only connector;
6. SDK validation и data-readiness assessment;
7. остановка расчёта при `blocked` либо детерминированный основной/stress forecast;
8. запись бухгалтерского snapshot и fiscal analysis history;
9. построение окна из того же синхронизированного snapshot.

Не выполняются автоматически: seed demo data, импорт из 1С, импорт CSV банка, повторная синхронизация, загрузка нормативных документов, AI extraction, перенос regulatory package, импорт package в Core, создание/активация правил, резервное копирование и обновление программы.

## 8. Как устроено хранение и повторные расчёты

Текущая реализация не использует алгоритм «один полный baseline, затем всегда считать только delta».

- Каждый вызов бухгалтерского connector возвращает самодостаточный `FinancialSnapshot`.
- Если подключён recorder, весь снимок записывается ещё раз как canonical JSON.
- Возможность cursor/incremental request предусмотрена интерфейсом, но не подключена к startup orchestration.
- Последующий расчёт при следующем запуске снова читает текущую прототипную БД; сохранённый снимок используется для аудита, а не как автоматическая база следующего расчёта.
- Бухгалтерская, банковская и аналитическая истории append-only. Для них нет retention, поэтому объём растёт приблизительно линейно с размером снимка и количеством запусков.

Это безопасно для воспроизводимости прототипа, но перед эксплуатацией нужны политика хранения, оценка объёма на реальном экспорте, дедупликация/сжатие или иной способ сохранения baseline + changes без потери аудита.

## 9. Автоматические проверки и тесты

В текущем окружении используются Ruff и Pytest. Набор содержит 91 test function и 99 test cases с учётом параметризации.

Покрытые группы:

- cash forecast, rounding, horizons и gaps;
- end-to-end synchronization для ready/limited/blocked;
- fiscal applicability, calculation, reconciliation, penalties, fines и stress forecast;
- immutable rule registry, supersession и analysis history;
- snapshot compatibility, hashes и immutable database triggers;
- 1C mapper shell и integration SDK contracts;
- CSV bank ingestion, reconciliation и bank history;
- migrations новой и существующей БД;
- UI smoke tests в Qt offscreen mode;
- Core no-network import/dependency policy;
- package dependency directions и wheel boundary helper;
- regulatory source allowlist, package schema, signatures, tamper/expiry/replay/quarantine;
- trusted-key bootstrap, rotation, revocation и retention;
- статическая проверка содержимого двух Windows deployment scripts.

Тесты не включают:

- реальную 1С;
- реальный банк или банковский API;
- официальные сайты Грузии;
- реальные налоговые golden cases;
- AI/RAG;
- Windows executable build и запуск;
- реальное применение Windows ACL/firewall/S4U;
- code signing/installer;
- нагрузочные, длительные, backup/restore и penetration tests.

## 10. Что работает в Windows-сборке

Фактически проверенной Windows-сборки пока нет, поэтому утверждать, что пользовательские функции работают в `.exe`, нельзя.

В репозитории подготовлены:

- отдельные PyInstaller specs для `FinRadarCore` и `FinRadarMonitor`;
- включение Alembic migrations в Core artifact;
- создание mutable Core DB под platform user-data directory во frozen mode;
- build-time проверки запрещённых packages и известных networking binaries;
- PowerShell build script для Python 3.13 на Windows;
- provisioning scripts для restricted Monitor user, S4U task, ACL, firewall, initial trust и cross-identity probes.

Они имеют статус **Implemented but not fully tested**, пока не выполнены на чистой поддерживаемой Windows VM. В текущем окружении macOS `PyInstaller` не установлен; кросс-сборка Windows средствами PyInstaller невозможна.

## 11. Известные ограничения и риски

1. **Нет реальных входных данных.** Основная демонстрация основана на локальном demo database; реальные 1С и банк не подключены.
2. **Нет реальной фискальной корректности.** Generic engine тестируется на вымышленных формулах. Он не подтверждает соответствие законодательству Грузии.
3. **Нет автоматического обновления законодательства.** Allowlist и signed package transport не заменяют downloader, extraction, legal review и rule mapping.
4. **Windows boundary не проверена.** Скрипты могут содержать platform-specific ошибки, которые статические тесты не выявят.
5. **Installer trust отсутствует.** Initial-key bootstrap безопасен только после ACL provisioning и из подписанного installer; самого installer нет.
6. **SQLite не зашифрован.** Любой субъект с доступом к файлу может прочитать финансовые данные.
7. **История растёт без retention.** Полные snapshots записываются повторно; нет capacity policy и vacuum/compaction workflow.
8. **Нет multi-company selection.** Прототипный connector выбирает первую компанию по `created_at`.
9. **Нет FX policy.** Любая несовпадающая валюта блокирует консолидацию.
10. **Нет transactional orchestration всего запуска.** Snapshot может быть записан до анализа; отдельные commits обеспечивают аудит этапов, но не атомарность единой бизнес-операции.
11. **Нет фонового обновления и UX подключения.** Для обычного пользователя ещё нельзя выбрать 1С/банк и нажать одну кнопку.
12. **Список запрещённых network imports конечен.** Статический тест снижает риск случайной зависимости, но не заменяет OS firewall и executable network tests.
13. **Private key хранится файлом.** До DPAPI/CNG/HSM защита зависит от filesystem permissions/ACL.
14. **Принятый regulatory candidate не влияет на расчёт.** Это безопасное текущее поведение, но функциональная цепочка не завершена.
15. **Отсутствует юридический review workflow.** Нельзя штатно зафиксировать, кто и на каком основании проверил и активировал реальное правило.
16. **Нет встроенного backup/restore.** Повреждение или потеря локального диска не обрабатываются продуктом.

## 12. Структура файлов

```text
finradar/
├── src/finradar/
│   ├── main.py                         # Core startup
│   ├── domain/                         # snapshot, banking, readiness, forecast, fiscal rules
│   ├── application/                    # synchronization, analysis, SDK, histories
│   ├── infrastructure/
│   │   ├── connectors/                 # demo, prototype SQLite, 1C shell, bank CSV
│   │   ├── database.py                 # SQLite paths and Alembic startup
│   │   ├── models.py                   # SQLAlchemy models
│   │   ├── *_history.py                # append-only snapshots/results
│   │   ├── fiscal_rule_registry.py      # rule versions and lifecycle
│   │   ├── regulatory_inbox.py          # signed package import/quarantine
│   │   ├── regulatory_trust_store.py    # trust bootstrap/rotation/revocation
│   │   └── regulatory_retention.py      # rejected-package retention
│   └── ui/main_window.py               # PySide6 window
├── packages/contracts/
│   └── src/finradar_contracts/          # package/signature/source/trust contracts
├── packages/monitor/
│   └── src/finradar_monitor/            # public DB, signing keys, package export
├── migrations/versions/                # 0001–0007
├── tests/                              # 21 test modules
├── tools/                              # distribution/frozen-boundary checks
├── packaging/windows/                  # PyInstaller specs and build script
├── deployment/windows/                 # ACL/firewall/task/trust/test scripts
├── docs/architecture/                  # ADR-001–ADR-008
├── data/finradar.db                    # local development DB; ignored working data
├── pyproject.toml                      # Core distribution and tooling
└── alembic.ini
```

## 13. Используемые технологии

| Компонент | Технология | Фактическое использование |
| --- | --- | --- |
| Язык | Python `>=3.13,<3.14` | Текущее окружение: Python 3.13.14 |
| Desktop UI | PySide6 6.11.1 / Qt | Окно Core и offscreen UI tests |
| ORM | SQLAlchemy 2.x | Core models, repositories и histories |
| Миграции | Alembic 1.x | Семь revisions, automatic upgrade at startup |
| Локальная БД Core | SQLite | Финансовые данные, snapshots, rules, audit, trust |
| Локальная БД Monitor | `sqlite3` stdlib | Только публичные regulatory documents |
| Криптография | `cryptography` 49.0.0, Ed25519, SHA-256 | Package signatures, trust records, content integrity |
| Data directories | platformdirs | Frozen Core user-data path |
| Packaging | setuptools, wheel, PyInstaller 6.21.0 в Windows requirements | Три distributions; Windows specs подготовлены |
| Качество | Ruff, Pytest, pytest-qt | Lint, unit/integration tests, UI smoke tests |
| PowerShell | Windows Task Scheduler, ACL API, Windows Firewall | Deployment templates, не проверенные на Windows VM |
| Pydantic | Core contract validation | Строгая загрузка каталогов обязательств, налоговых ставок и зарплатных правил |
| AI/RAG/vector DB | Нет | Не реализованы и не объявлены как runtime dependencies |

## 14. Минимальные условия перехода от прототипа к проверяемому пилоту

Следующие пункты являются не расширением функций, а условиями, без которых нельзя фактически проверить заявленную модель на реальном предприятии:

1. выбрать одну конкретную конфигурацию 1С и реализовать read-only transport с golden export fixtures;
2. подключить один локальный формат выписки конкретного банка к desktop workflow;
3. создать и проверить независимые Windows artifacts, ACL/firewall boundary и signed installer;
4. включить шифрование Core data или письменно принять ограничение только для обезличенного пилота;
5. реализовать downloader одного стабильного официального источника без AI;
6. связать accepted candidate с registry и создать обязательный review/activation workflow;
7. связать проверенный каталог ставок с локальным resolver применимости и проверить ограниченный набор правил Грузии на юридически подтверждённых golden cases;
8. только после этого добавлять AI extraction и объяснение как недоверенный вспомогательный слой.
