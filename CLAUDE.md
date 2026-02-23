# Python Coding Best Practices

## Python Version Compatibility

- Target Python 3.10+. Never use features introduced after Python 3.10 without a compatibility fallback.
- Common pitfalls:
  - `datetime.UTC` was added in Python 3.11. Use `datetime.timezone.utc` instead.
  - `StrEnum` was added in Python 3.11. Provide a compatibility shim or backport.
  - `type` statement (PEP 695) was added in Python 3.12. Use `TypeAlias` from `typing` instead.
  - `ExceptionGroup` / `except*` was added in Python 3.11. Avoid unless using the `exceptiongroup` backport.

## Variables, Loops and Indexes

- Variable names should have a minimum length of 3 characters. No exceptions: name your `for` loop indexes like `index_item`, your exceptions `exc` or more specific like `validation_error` when there are several layers of exceptions, and use `for key, value in ...` for key/value pairs.
- When looping on the keys of a dict, use `for key in the_dict` rather than `for key in the_dict.keys()`.
- Avoid inline for loops, unless it's ultra-simple and holds on one line.
- If you have a variable that will get its value differently through different code paths, declare it first with a type, e.g. `result: str` but DO NOT give it a default value like `result: str = ""` unless it's really justified. We want the variable to be unbound until all paths are covered, and the linters will help us avoid bugs this way.

## Enums

- When defining enums related to string values, always inherit from `StrEnum`.
- When you need the enum value as a string, don't use `str(enum_var)` or `enum_var.value`, just use `enum_var` itself — that is the point of using StrEnum.
- Never test equality to an enum value: use match/case, even to single out 1 case out of 10 cases. To avoid heavy match/case code in awkward places, add `@property` methods to the enum class such as `is_foobar()`. This prevents bugs: when new enum values are added the linter will complain about non-exhaustive matches. Use the `|` operator to group cases.
- Match/case constructs over enums should always be exhaustive. NEVER add a default `case _: ...`.

## Optionals

- Don't write things like `a = b if b else c`, write `a = b or c` instead.

## Imports

### Imports at the top of the file

- Import all necessary libraries at the top of the file.
- Do not import libraries in functions or classes unless in very specific cases that require a `# noqa: ...` comment to pass linting.
- Do not bother with ordering the imports or removing unused imports — let the linter (e.g. Ruff) handle it.
- `if TYPE_CHECKING:` blocks must always be the **last** block in the imports section, placed after all regular imports.

### No re-exports in `__init__.py`

- Do NOT fill `__init__.py` files with re-exports.
- Always use direct full-path imports everywhere.

## Typing

### Always Use Type Hints

- Every function parameter must be typed.
- Every function return must be typed.
- Use type hints for all variables where type is not obvious.
- Use lowercase generic types: `dict[]`, `list[]`, `tuple[]`.
- Use type hints for all fields.
- Use `Field(default_factory=...)` for mutable defaults.
- Use `# pyright: ignore[specificError]` or `# type: ignore` only as a last resort. If you are sure about the type, prefer using `cast()` or creating a new typed variable.

### BaseModel / Pydantic Standards

- Use `BaseModel` and respect Pydantic v2 standards.
- Use the modern `ConfigDict` when needed, e.g. `model_config = ConfigDict(extra="forbid", strict=True)`.
- Keep models focused and single-purpose.
- For list fields with non-string items in BaseModels, use a typed `default_factory` to avoid linter complaints:
  ```python
  from pydantic import BaseModel, Field

  class MyModel(BaseModel):
      names: list[str] = Field(default_factory=list)  # OK for strings
      numbers: list[int] = Field(default_factory=list)
  ```

## Factory Pattern

- Use factory pattern for object creation when dealing with multiple implementations.
- Name factory methods `make_from_...` or similar.

## Error Handling

- Always catch exceptions at the place where you can add useful context to them.
- Use try/except blocks with specific exceptions.
- Convert third-party exceptions to custom ones, except in pydantic validators where you can raise a `ValueError` or a `TypeError`.
- NEVER catch the generic `Exception`, only catch specific exceptions, except at the root of CLI commands.
- Always add `from exc` to the exception raise statements.
- Always write the error message as a variable before raising it, for cleaner error traces.

```python
try:
    manager.setup()
except LibraryNotFoundError as exc:
    msg = "The library could not be found, please check your configuration"
    raise SetupError(msg) from exc
```

## Documentation

### Docstring Format

```python
def process_image(image_path: str, size: tuple[int, int]) -> bytes:
    """Process and resize an image.

    Args:
        image_path: Path to the source image
        size: Tuple of (width, height) for resizing

    Returns:
        Processed image as bytes
    """
    pass
```

### Class Documentation

```python
class ImageProcessor:
    """Handles image processing operations.

    Provides methods for resizing, converting, and optimizing images.
    """
```

## Writing Tests

### General Rules

- NEVER use `unittest.mock`. Always use pytest-mock: `from pytest_mock import MockerFixture`.
- NEVER put more than one TestClass into a test module.

### Test File Structure

- Name test files with `test_` prefix.
- Place test files in the appropriate test category directory:
  - `tests/unit/` — for unit tests that test individual functions/classes in isolation
  - `tests/integration/` — for integration tests that test component interactions
  - `tests/e2e/` — for end-to-end tests that test complete workflows
- Do NOT add `__init__.py` files to test directories. Test directories do not need to be Python packages.
- Fixtures are defined in `conftest.py` modules at different levels of the hierarchy; their scope is handled by pytest.
- Test data is placed inside `test_data.py` at different levels of the hierarchy. Their content is all constants, regrouped inside classes to keep things tidy.
- Always put tests inside Test classes: 1 TestClass per module.
- Put fixtures into `conftest.py` files for easy sharing.

### Test Class Structure

- Always group the tests of a module into a test class:

```python
@pytest.mark.asyncio(loop_scope="class")
class TestFooBar:
    @pytest.mark.parametrize(
        "topic, test_case_blueprint",
        [
            TestCases.CASE_1,
            TestCases.CASE_2,
        ],
    )
    async def test_processing(
        self,
        request: FixtureRequest,
        topic: str,
        test_case_blueprint: Blueprint,
    ):
        # Test implementation
```

- Never more than 1 class per test module.
- When testing one method, if possible, limit the number of test functions, but with different test cases in parameters.

### Test Data Organization

- Create a `test_data.py` file in the proper test directory.
- Avoid initializing a default mutable value within a class instance; use `ClassVar` instead.
- Provide a topic for each test case for convenience.

### Best Practices for Testing

- Use strong asserts: test value, not just type and presence.
- Use `parametrize` for multiple test cases.
- Test both success and failure cases.
- Check output structure and content.
- Use meaningful test case names.
- Include concise docstrings explaining test purpose, but not on top of the file and not on top of the class.
- Log outputs for debugging.

## Test-Driven Development

1. **Write a Test First**
2. **Write the Code** — Implement the minimum amount of code needed to pass the test. Keep it simple, don't write more than needed.
3. **Run Linting and Type Checking**
4. **Validate Tests**

The key to TDD is writing the test first and letting it drive your implementation. Always run the full test suite and quality checks before considering a feature complete.

## Post-Coding Checklist

After finishing any code change, always run:
```bash
make fui && make cc
```
This fixes unused imports, cleans caches, formats, lints, and type-checks. Do not consider a task done until this passes.
