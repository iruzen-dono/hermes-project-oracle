# hermes-project-oracle → project-oracle

**This package was renamed to [`project-oracle`](https://pypi.org/project/project-oracle/) in 3.0.0.**

This release ships **no code**. It exists for one reason: so that
`pip install -U hermes-project-oracle` moves an existing install onto the new
name instead of leaving it on a frozen 2.x. The five `oracle-*` commands arrive
from the dependency.

```bash
# new installs
pipx install project-oracle

# already on the old name — this upgrade pulls project-oracle automatically
pipx upgrade hermes-project-oracle
# or
pip install --upgrade hermes-project-oracle
```

No further releases will be published under this name.
