# DynamicAPIClient

[![CI](https://github.com/stuart23/dynamicapiclient/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/stuart23/dynamicapiclient/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/stuart23/dynamicapiclient/graph/badge.svg?branch=main)](https://codecov.io/gh/stuart23/dynamicapiclient)

Generate **Django-like** model classes from an **OpenAPI 2** or **OpenAPI 3** document, or a **GraphQL schema** (SDL or introspection JSON). Pass the spec to `api_make` as a **`pathlib.Path`**, a **string path** to a file on disk, or an **`http` / `https` URL** that returns the document. OpenAPI schemas under `definitions` (v2) or `components.schemas` (v3) become models with `.objects` wired to REST paths. GraphQL **object types** become models whose `.objects` issues `query` / `mutation` operations against a single HTTP endpoint (default `POST /graphql`).

## Install

The **PyPI distribution** is [`dynamicapiclient`](https://pypi.org/project/dynamicapiclient/) (`pip install dynamicapiclient`). The **Python import package** remains `dynamicapiclient` (`import dynamicapiclient`). This project is referred to as **DynamicAPIClient** in documentation.

```bash
pip install -e .
# or, with dev dependencies:
pip install -e ".[dev]"
# GraphQL support (graphql-core):
pip install -e ".[graphql]"
```

Requires Python 3.10+. GraphQL requires the optional `graphql` extra (`graphql-core`).

**GitHub:** badges and links in this README use the repository name **`dynamicapiclient`**. After you [rename the repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository) on GitHub to match, update **PyPI → Publishing → trusted publisher** with the new repository path if you use OIDC publishing.

## Quick start (fixture spec)

This repo includes a sample OpenAPI 3 spec at [`tests/fixtures/library_oas3.yaml`](tests/fixtures/library_oas3.yaml). It describes a small “library” API with `Author` and `Book` schemas and paths under `https://api.example.com/v1`.

`api_make` accepts the spec as a **`Path`**, a **string path**, or a **URL**:

```python
from pathlib import Path

from dynamicapiclient import api_make  # or: from dynamicapiclient import apiMake

# pathlib.Path (typical in application code)
MyAPI = api_make(Path("tests/fixtures/library_oas3.yaml"))

# Same file as a string path (relative or absolute on your machine)
MyAPI = api_make("tests/fixtures/library_oas3.yaml")

# HTTPS URL (fetches the spec over the network; example: raw file on GitHub)
MyAPI = api_make(
    "https://raw.githubusercontent.com/stuart23/dynamicapiclient/"
    "refs/heads/main/tests/fixtures/library_oas3.yaml"
)
```

The live fixture used in tests is also available at  
[library_oas3.yaml on `main`](https://raw.githubusercontent.com/stuart23/dynamicapiclient/refs/heads/main/tests/fixtures/library_oas3.yaml).

Discover generated models (works well in a REPL):

```python
dir(MyAPI.models)          # ['Author', 'Book']
list(MyAPI.models)         # model classes
MyAPI.models.model_names() # ('Author', 'Book')
```

The spec’s `servers[0].url` is used as the HTTP base URL unless you override it:

```python
MyAPI = api_make(Path("tests/fixtures/library_oas3.yaml"), base_url="http://localhost:8000/v1")
```

### Creating and reading resources

The fixture marks `name` and `email` as required on `Author`, and `title` and `author_id` on `Book`. **Your server must actually implement** the described paths (`POST /authors`, `GET /authors/{author_id}`, `POST /books`, etc.); the YAML file is only the contract.

```python
author = MyAPI.models.Author.objects.create(
    name="J.R.R. Tolkien",
    email="tolkien@example.com",
)

book = MyAPI.models.Book.objects.create(
    title="The Hobbit",
    author_id=author.pk,
)
```

**Note:** In `library_oas3.yaml`, `Book` only defines `id`, `title`, and `author_id`. Pass only fields that appear in the schema (extra fields raise validation errors). This fixture uses an integer `author_id`, not a nested `author=` relation object.

Other useful calls:

```python
same = MyAPI.models.Author.objects.get(pk=author.pk)
for a in MyAPI.models.Author.objects.filter(name="J.R.R. Tolkien"):
    print(a.pk, a._data["email"])

MyAPI.models.Author.objects.update(same, email="tolkien@tolkien.estate")
MyAPI.models.Author.objects.delete(same)
```

Close the underlying HTTP client when you are done (optional but good practice):

```python
MyAPI.close()
# or: with api_make(...) as MyAPI: ...
```

## Authentication

DynamicAPIClient does not read OpenAPI `security` / `securitySchemes` or GraphQL custom directives to sign requests for you. **You supply credentials** the same way you would with plain HTTP:

### Default headers on every request

Pass a `headers` dict to `api_make()`. Those headers are sent on **every** REST call and **every** GraphQL POST (the client passes them on each `httpx` request).

```python
from pathlib import Path

spec = Path("tests/fixtures/library_oas3.yaml")
MyAPI = api_make(
    spec,
    headers={"Authorization": "Bearer YOUR_ACCESS_TOKEN"},
)
```

Other common patterns:

```python
# API key in a header
api_make("tests/fixtures/library_oas3.yaml", headers={"X-API-Key": "secret"})

# Basic auth (raw header; or use http_client below)
import base64

token = base64.b64encode(b"user:pass").decode()
api_make("tests/fixtures/library_oas3.yaml", headers={"Authorization": f"Basic {token}"})
```

Use the header names and formats your API expects (many OpenAPI specs document them under `components.securitySchemes`—copy the scheme into `headers` yourself).

### Custom `httpx.Client` (Auth hooks, cookies, proxies)

For flows that fit [`httpx`’s `Auth` API](https://www.python-httpx.org/advanced/authentication/) (e.g. custom signing, OAuth2 helpers from extensions), build an `httpx.Client` and pass `http_client=...` to `api_make`. Keep `base_url` aligned with that client’s base URL. The `headers` argument is still applied on each request, so you can combine default headers with client-level configuration.

```python
import httpx
from pathlib import Path

from dynamicapiclient import api_make

client = httpx.Client(
    base_url="https://api.example.com/v1",
    headers={"Authorization": "Bearer ..."},
)
MyAPI = api_make(
    Path("tests/fixtures/library_oas3.yaml"),
    http_client=client,
    base_url="https://api.example.com/v1",
)
```

### Loading from a URL

Any `http`/`https` string that is not a local path is fetched as the spec body:

```python
MyAPI = api_make("https://example.com/openapi.yaml")
```

The [library fixture on GitHub](https://raw.githubusercontent.com/stuart23/dynamicapiclient/refs/heads/main/tests/fixtures/library_oas3.yaml) is a concrete OpenAPI 3 example you can pass directly to `api_make` (see Quick start above).

### Swagger 2 example

[`tests/fixtures/swagger2_library.json`](tests/fixtures/swagger2_library.json) defines a `Widget` model. Load it the same way; Swagger 2 uses `host` + `basePath` + `schemes` for the base URL, or pass `base_url=...` explicitly.

## GraphQL schema (SDL or introspection JSON)

Install `graphql-core` (`pip install "dynamicapiclient[graphql]"`). Point `api_make` at a `.graphql` / `.gql` file, a JSON introspection export (`data.__schema` or bare `__schema`), or a URL whose body looks like GraphQL SDL or introspection. For local files or payloads with no server URL, pass `base_url=` to the HTTP server root. If you load the schema from an `http(s)` URL, the URL’s **origin** (scheme + host) is used as the default API base unless you pass `base_url=` (which overrides and is logged at INFO).

```python
from pathlib import Path

from dynamicapiclient import api_make

schema_path = Path("tests/fixtures/library.graphql")
GQL = api_make(
    schema_path,
    base_url="https://api.example.com",
    graphql_path="/graphql",  # default; POST JSON { "query", "variables" }
    headers={"Authorization": "Bearer YOUR_TOKEN"},  # same as OpenAPI
)
author = GQL.models.Author.objects.create(name="Ada", email="ada@example.com")
```

DynamicAPIClient infers operations using common patterns:

- **List**: a `Query` field whose return type is a list of the object type (e.g. `authors: [Author!]!`), optional `filter()` args match declared GraphQL arguments on that field.
- **Get**: a `Query` field returning the type with an `id: ID!` (or `authorId`-style) argument.
- **Create / update / delete**: `Mutation` fields whose names start with `create` / `add`, `update` / `edit`, or `delete` / `remove`, with `input` arguments for writes and `ID` arguments where needed.

If your API uses different names, DynamicAPIClient may not find an operation; you will get a clear `DynamicAPIClientModelError`.

## How it works (short)

- Schemas become Python types on `api.models.<Name>`.
- **OpenAPI**: CRUD routes are **inferred** from paths whose bodies or responses reference that schema.
- **GraphQL**: CRUD maps to `query` / `mutation` documents sent to `graphql_path`, using the heuristics described above.
- If the spec does not expose a clear operation for a model, calling the missing operation raises a clear `DynamicAPIClientModelError`.

For full behavior and edge cases, see the test suite under `tests/`.

## Tests, coverage, and pre-commit

CI-style checks use **≥90%** coverage on `dynamicapiclient` (see `pyproject.toml`). Run:

```bash
pytest -q --cov=dynamicapiclient --cov-fail-under=90
```

One test (`tests/test_api_make_sources.py`) fetches the public OpenAPI fixture from raw GitHub and is marked **`network`** (outbound HTTPS). To skip it offline: `pytest -m "not network" -q --cov=dynamicapiclient --cov-fail-under=90`.

[GitHub Actions](https://github.com/stuart23/dynamicapiclient/actions/workflows/ci.yml) runs the same suite on Python 3.10–3.13 and uploads coverage to [**Codecov**](https://codecov.io/gh/stuart23/dynamicapiclient) via **OIDC** (no `CODECOV_TOKEN` needed on the main repo). Add the project in Codecov once so the badge and graphs populate. Forks or private mirrors may need a **`CODECOV_TOKEN`** secret—see [Codecov’s docs](https://docs.codecov.com/docs/codecov-tokens).

With a **Git** checkout, install [`pre-commit`](https://pre-commit.com/) (`pip install pre-commit` or use the `dev` extra) and run `pre-commit install` so commits run the same pytest command via [`.pre-commit-config.yaml`](.pre-commit-config.yaml).
