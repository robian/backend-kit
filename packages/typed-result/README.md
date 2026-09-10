# typed-result

A small `Result[T, E]` for expected failures in strictly typed Python code.
`Result` is the closed union `Ok[T] | Err[E]`, so type checkers can verify both
the result variant and domain-error handling exhaustively.

```python
import dataclasses

from typed_result import Err
from typed_result import Ok
from typed_result import Result


@dataclasses.dataclass(frozen=True, slots=True)
class ProductNotFound:
    product_id: int


def find_product(product_id: int) -> Result[str, ProductNotFound]:
    if product_id == 42:
        return Ok("Desk lamp")
    return Err(ProductNotFound(product_id))


match find_product(42):
    case Ok(value=product):
        print(product)
    case Err(error=error):
        print(f"Product {error.product_id} was not found")
```
