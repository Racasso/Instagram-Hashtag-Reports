# Raporty hashtagów z zakładki Tagged na Instagramie

Usługa udostępnia REST API do tworzenia raportów z publicznych wpisów oznaczonych na profilu Instagram. Pobiera wpisy z zakładki **Tagged** wybranego profilu, wyszukuje w nich wskazany hashtag i szereguje dopasowania według sumy polubień oraz komentarzy.

Przykładowy zakres projektu to profil `boxpleasepl` i hashtag `#smakujemyfivio`. Pobieranie wykonuje aktor Apify, zadania przetwarza osobny worker, a raporty są przechowywane w MongoDB.

## Najważniejsze funkcje

- Tworzenie raportu dla profilu, hashtagu i przedziału dat.
- Pobieranie wpisów z zakładki Tagged aktorem Apify `instagram-data-api/instagram-tagged-scraper`.
- Dopasowywanie hashtagu z listy hashtagów zwróconej przez aktora, z dodatkowym sprawdzeniem podpisu wpisu.
- Filtrowanie wyników po dacie publikacji i usuwanie duplikatów na podstawie adresu wpisu.
- Ranking malejący według `likes + comments`.
- Zapis kolejki zadań i wyników w MongoDB oraz możliwość uruchomienia kilku workerów.
- Dokumentacja i formularz API dostępne przez Swagger UI.

## Wymagania

Do uruchomienia wariantu Docker potrzebne są:

- Docker z obsługą `docker compose`;
- token `APIFY_TOKEN` z Apify Console;
- dostęp sieciowy do usługi Apify.

Compose uruchamia MongoDB 8.0 razem z API i workerem. Do uruchomienia bez Dockera potrzebny jest Python 3.12 oraz działający serwer MongoDB. Zależności Pythona są przypięte w [`requirements.txt`](requirements.txt).

## Instalacja i uruchomienie w Dockerze

Wykonuj polecenia w katalogu repozytorium, w którym znajduje się `docker-compose.yml`.

1. Utwórz lokalny plik konfiguracyjny, jeśli jeszcze go nie ma:

   ```bash
   test -f .env || cp .env.example .env
   ```

2. Otwórz `.env` i zastąp `uzupelnij_lokalnie` tokenem z Apify Console. Nie wklejaj tokenu do README ani do `.env.example`. Plik `.env` jest wykluczony z Git i z kontekstu budowania obrazu.

3. Zbuduj obrazy i uruchom usługi w tle:

   ```bash
   docker compose up --build -d
   ```

4. Sprawdź, czy kontenery działają:

   ```bash
   docker compose ps
   ```

API jest wystawione na porcie `8000`, a MongoDB na porcie `27017`. Dane MongoDB są przechowywane w wolumenie Compose `mongo_data`.

## Konfiguracja

Przykładowe wartości znajdują się w [`.env.example`](.env.example). W Compose oba procesy aplikacji wczytują `.env`; adres MongoDB jest ustawiany dla sieci Compose na `mongodb://mongo:27017`.

| Zmienna | Wartość przykładowa | Znaczenie |
| --- | --- | --- |
| `APIFY_TOKEN` | `uzupelnij_lokalnie` | Token używany przez workera do wywołania Apify. Wpisz go lokalnie w `.env`. |
| `APIFY_ACTOR_ID` | `instagram-data-api/instagram-tagged-scraper` | Identyfikator aktora pobierającego wpisy z zakładki Tagged. |
| `MAX_APIFY_COST_USD` | `0.20` | Maksymalny koszt pojedynczego runu przekazywany do klienta Apify. |
| `APIFY_PRICE_PER_1000_RESULTS_USD` | `0.37` | Szacunkowa stawka używana do ograniczenia liczby pobieranych wpisów względem limitu kosztu. Nie jest gwarancją ceny rozliczenia. |
| `APIFY_RUN_TIMEOUT_SECONDS` | `300` | Limit czasu runu aktora. |
| `APIFY_WAIT_SECONDS` | `360` | Czas oczekiwania klienta Apify na zakończenie runu. |
| `MONGODB_URI` | `mongodb://mongo:27017` | Adres MongoDB w sieci Compose. Przy uruchomieniu lokalnym ustaw `mongodb://localhost:27017`. |
| `MONGODB_DATABASE` | `instagram_reports` | Nazwa bazy MongoDB używanej przez aplikację. |
| `WORKER_POLL_SECONDS` | `2` | Odstęp między sprawdzeniami kolejki, gdy nie ma oczekującego zadania. |
| `LOG_LEVEL` | `INFO` | Poziom logowania API i workera. |

Limit wyników w żądaniu to maksymalnie 100. Worker zmniejsza efektywny limit także wtedy, gdy limit kosztu i skonfigurowana stawka wskazują na mniejszą liczbę wpisów. Rzeczywisty koszt zależy od rozliczenia Apify i jest zapisywany w raporcie, jeśli aktor go zwróci.

## Użycie API przez Swagger

Otwórz [Swagger UI](http://localhost:8000/docs). W sekcji `POST /reports` kliknij **Try it out**, wprowadź żądanie i wybierz **Execute**.

Przykładowe żądanie:

```json
{
  "profile_url": "https://www.instagram.com/boxpleasepl/tagged/",
  "tag": "#smakujemyfivio",
  "published_from": "2026-10-01T00:00:00Z",
  "published_to": "2026-10-31T23:59:59Z",
  "max_results": 50
}
```

Wartości dat są przykładowe — ustaw okres, który chcesz analizować. Obie daty muszą zawierać strefę czasową; zakres jest włączny. Aplikacja przyjmuje nazwę profilu, URL profilu lub URL jego zakładki `/tagged/`. Pola `platform`, `source` i `content_type` mają wartości domyślne, więc nie trzeba ich dodawać do żądania. `max_results` domyślnie wynosi 50 i może mieć wartość od 1 do 100.

`POST /reports` zwraca status HTTP `202 Accepted` oraz identyfikator raportu, na przykład:

```json
{
  "id": "<report_id>",
  "status": "queued"
}
```

Odczytaj raport przez `GET /reports/{report_id}`. W Swaggerze rozwiń ten endpoint, kliknij **Try it out**, wstaw identyfikator i wybierz **Execute**. Powtarzaj odczyt, aż status będzie `done` albo `failed`. Statusy pośrednie to `queued` i `running`.

Możesz też sprawdzić API bez Swaggera:

```bash
curl http://localhost:8000/health
```

Oczekiwana odpowiedź endpointu zdrowia:

```json
{"status":"ok"}
```

Wywołanie `POST /reports` uruchamia prawdziwy run Apify, a nie symulację. Każde nowe zapytanie może więc wiązać się z kosztem. Limit pojedynczego runu z konfiguracji przykładowej wynosi `0.20` USD.

## Jak działa raport

1. API waliduje profil, hashtag i daty oraz zapisuje zapytanie w MongoDB ze statusem `queued`.
2. Worker pobiera najstarsze oczekujące zadanie i oznacza je jako `running`.
3. Aktor pobiera ograniczoną liczbę wpisów z zakładki Tagged. Granice dat są przekazywane do aktora jako daty kalendarzowe.
4. Aplikacja dopasowuje hashtag i dokładny przedział czasu do pobranych wyników, usuwa powtórzenia URL-i i oblicza ranking.
5. Wynik trafia do dokumentu raportu, a status zmienia się na `done`. W przypadku wyjątku worker ustawia `failed`; szczegóły sprawdź w logach.

Zakres dat jest dodatkowo sprawdzany przez aplikację wśród pobranych wpisów. Ponieważ liczba pobieranych wpisów jest ograniczona przez `max_results` i limit kosztu, raport nie gwarantuje kompletności całego okresu, jeśli pasujących wpisów jest więcej niż pobrany limit.

### Pola wyniku

Raport zawiera zapytanie, status, znaczniki czasu, podsumowanie, listę wpisów oraz — po zakończeniu pobierania — informacje o runie Apify.

- `summary.posts_in_period` — liczba dopasowanych wpisów po filtrach.
- `summary.ranked_by` — kryterium rankingu, obecnie `likes_plus_comments`.
- `summary.total_likes` i `summary.total_comments` — sumy liczników. Wartość będzie `null`, gdy dla co najmniej jednego wpisu w danej sumie brakuje metryki.
- `posts[].metrics.engagement_count` — suma polubień i komentarzy; pozostaje `null`, jeśli brakuje którejś z tych wartości.
- `posts[].metrics.engagement_rate_percent` — `engagement_count / followers_count × 100`, jeśli aktor zwróci dodatnią liczbę obserwujących; w przeciwnym razie `null`.
- `apify.cost_usd` — koszt runu zwrócony przez Apify; może być `null`.

Metryki są odczytem z chwili pobrania. Projekt nie wylicza zasięgu, wyświetleń, konwersji ani zmian historycznych. Ponowne wysłanie identycznego zapytania zwraca ten sam raport zamiast tworzyć duplikat zadania.

## Komendy i procesy

| Polecenie | Działanie |
| --- | --- |
| `docker compose up --build -d` | Buduje obrazy API i workera, a następnie uruchamia usługi w tle. |
| `docker compose ps` | Pokazuje stan kontenerów Compose. |
| `docker compose logs -f worker` | Wyświetla i śledzi logi workera. Przy statusie `failed` zacznij diagnostykę tutaj. |
| `docker compose up --build -d --scale worker=3` | Uruchamia trzy instancje workera. Worker atomowo przejmuje zadania z MongoDB, aby instancje nie przetwarzały tego samego raportu. |
| `python -m app.worker` | Uruchamia proces workera poza Dockerem; wymaga zmiennych środowiskowych i dostępnej bazy MongoDB. |
| `uvicorn app.api:app --reload` | Uruchamia lokalny serwer API z automatycznym przeładowaniem kodu. |
| `python -m pytest -q` | Uruchamia testy jednostkowe. |

W repozytorium nie ma osobnych skryptów powłoki; API, pobieranie, baza i worker są zaimplementowane w modułach `app/`.

## Uruchomienie lokalne bez Dockera

Ta ścieżka wymaga zainstalowanego i uruchomionego MongoDB. W `.env` ustaw `MONGODB_URI=mongodb://localhost:27017`.

W pierwszym terminalu utwórz środowisko Python i zainstaluj zależności:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Załaduj zmienne z `.env` i uruchom API:

```bash
set -a && source .env && set +a
uvicorn app.api:app --reload
```

W drugim terminalu aktywuj to samo środowisko, załaduj `.env` i uruchom worker:

```bash
source .venv/bin/activate
set -a && source .env && set +a
python -m app.worker
```

## Testy i diagnostyka

Testy można uruchomić po zainstalowaniu zależności:

```bash
python -m pytest -q
```

Obecny zestaw sprawdza normalizację, dopasowanie hashtagu, filtrowanie dat, ranking na zapisanej próbce aktora oraz idempotencję zapisu raportu. Próbka znajduje się w [`tests/fixtures/instagram_tagged_boxpleasepl_sample.json`](tests/fixtures/instagram_tagged_boxpleasepl_sample.json) i jest zrzutem danych zebranych w określonym czasie; liczniki mogą być inne przy kolejnym pobraniu.

Przydatne kontrole:

- Jeśli API nie odpowiada, sprawdź kontenery poleceniem `docker compose ps` i health check pod `http://localhost:8000/health`.
- Jeśli raport długo pozostaje `queued` lub ma status `failed`, sprawdź `docker compose logs -f worker` oraz to, czy `.env` zawiera poprawny token Apify.
- Jeśli Docker Compose zgłasza brak pliku `.env`, utwórz go zgodnie z krokiem konfiguracji.

## Struktura repozytorium

```text
.
├── app/
│   ├── api.py           # endpointy FastAPI i Swagger
│   ├── apify.py         # wywołanie aktora Apify
│   ├── db.py            # MongoDB, indeksy i kolejka raportów
│   ├── models.py        # walidacja, normalizacja i modele odpowiedzi
│   └── worker.py        # pobieranie i przetwarzanie raportów
├── tests/
│   ├── fixtures/        # próbka odpowiedzi aktora
│   ├── test_idempotency.py
│   └── test_metrics.py
├── .env.example         # przykładowe zmienne środowiskowe
├── .gitignore           # wyklucza m.in. lokalny .env
├── .dockerignore        # wyklucza m.in. .env z obrazu
├── docker-compose.yml   # API, worker i MongoDB
├── Dockerfile           # obraz Python 3.12 dla API i workera
├── requirements.txt     # przypięte zależności Pythona
└── README.md
```

## Powiązana dokumentacja

- [Aktor Instagram Tagged Scraper w Apify Store](https://apify.com/instagram-data-api/instagram-tagged-scraper)
- [Cennik Apify](https://apify.com/pricing)
- Dokumentacja API aplikacji: `http://localhost:8000/docs` po uruchomieniu usług.

## Źródła informacji i elementy do uzupełnienia

README opracowano na podstawie `app/api.py`, `app/apify.py`, `app/db.py`, `app/models.py`, `app/worker.py`, testów i próbki w `tests/`, a także `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `.env.example`, `.gitignore` i `.dockerignore`.

W repozytorium nie ma pliku licencji, potwierdzonych danych autorów ani zrzutów ekranu. Przed publikacją na GitHubie uzupełnij licencję i autorów, jeśli mają być podani. Nie dodawaj tokenu Apify do repozytorium.
