# DynamicAPIClient

[![CI](https://github.com/stuart23/dynamicapiclient/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/stuart23/dynamicapiclient/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/stuart23/dynamicapiclient/graph/badge.svg?branch=main)](https://codecov.io/gh/stuart23/dynamicapiclient)

Generate **Django-like** model classes from an **OpenAPI 2** or **OpenAPI 3** document, or a **GraphQL schema** (SDL or introspection JSON), as a URL or local file. OpenAPI schemas under `definitions` (v2) or `components.schemas` (v3) become models with `.objects` wired to REST paths. GraphQL **object types** become models whose `.objects` issues `query` / `mutation` operations against a single HTTP endpoint (default `POST /graphql`).

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

### Tests, coverage, and pre-commit

CI-style checks use **≥90%** coverage on `dynamicapiclient` (see `pyproject.toml`). Run:

```bash
pytest -q --cov=dynamicapiclient --cov-fail-under=90
```

[GitHub Actions](https://github.com/stuart23/dynamicapiclient/actions/workflows/ci.yml) runs the same suite on Python 3.10–3.13 and uploads coverage to [**Codecov**](https://codecov.io/gh/stuart23/dynamicapiclient) via **OIDC** (no `CODECOV_TOKEN` needed on the main repo). Add the project in Codecov once so the badge and graphs populate. Forks or private mirrors may need a **`CODECOV_TOKEN`** secret—see [Codecov’s docs](https://docs.codecov.com/docs/codecov-tokens).

With a **Git** checkout, install [`pre-commit`](https://pre-commit.com/) (`pip install pre-commit` or use the `dev` extra) and run `pre-commit install` so commits run the same pytest command via [`.pre-commit-config.yaml`](.pre-commit-config.yaml).

## Quick start (fixture spec)

This repo includes a sample OpenAPI 3 spec at [`tests/fixtures/library_oas3.yaml`](tests/fixtures/library_oas3.yaml). It describes a small “library” API with `Author` and `Book` schemas and paths under `https://api.example.com/v1`.

Load the spec from disk and build the API object:

```python
from pathlib import Path

from dynamicapiclient import api_make  # or: from dynamicapiclient import apiMake

spec_path = Path("tests/fixtures/library_oas3.yaml")
# Or an absolute path on your machine.

MyAPI = api_make(spec_path)
```

Discover generated models (works well in a REPL):

```python
dir(MyAPI.models)          # ['Author', 'Book']
list(MyAPI.models)         # model classes
MyAPI.models.model_names() # ('Author', 'Book')
```

The spec’s `servers[0].url` is used as the HTTP base URL unless you override it:

```python
MyAPI = api_make(spec_path, base_url="http://localhost:8000/v1")
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

### Headers (e.g. auth)

```python
MyAPI = api_make(
    spec_path,
    headers={"Authorization": "Bearer YOUR_TOKEN"},
)
```

### Loading from a URL

```python
MyAPI = api_make("https://example.com/openapi.yaml")
```

### Swagger 2 example

[`tests/fixtures/swagger2_library.json`](tests/fixtures/swagger2_library.json) defines a `Widget` model. Load it the same way; Swagger 2 uses `host` + `basePath` + `schemes` for the base URL, or pass `base_url=...` explicitly.

## GraphQL schema (SDL or introspection JSON)

Install `graphql-core` (`pip install "dynamicapiclient[graphql]"`). Point `api_make` at a `.graphql` / `.gql` file, a JSON introspection export (`data.__schema` or bare `__schema`), or a URL whose body looks like GraphQL SDL or introspection. You **must** pass `base_url=` to the HTTP server root; SDL does not carry a server URL.

```python
from pathlib import Path

from dynamicapiclient import api_make

schema_path = Path("tests/fixtures/library.graphql")
GQL = api_make(
    schema_path,
    base_url="https://api.example.com",
    graphql_path="/graphql",  # default; POST JSON { "query", "variables" }
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
