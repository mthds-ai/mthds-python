# Contributing to mthds

Thank you for your interest in contributing! Contributions are very welcome. We appreciate first time contributors and we are happy help you get started. Join our community on [Discord](https://go.pipelex.com/discord) and feel free to reach out with questions in the #code-contributions and #contributions channels.

Everyone interacting in Discord, codebases, mailing lists, events, or any other Pipelex activities is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Please review it before getting started.

Most of the issues that are open for contributions are tagged with `good first issue` or `help-welcome`. If you see an issue that isn't tagged that you're interested in, post a comment with your approach, and we'll be happy to assign it to you. If you submit a fix that isn't linked to an issue you're assigned, there's chance it won't be accepted. Don't hesitate to ping the Pipelex team on Discord to discuss your choice of issue before getting to work.

We are open to contributions in all areas of the mthds package:

- **Bug fixes**: Crashes, incorrect output, performance issues
- **Feature**: New API, CLI flag, module, test coverage
- **Refactor**: Rethink architecture
- **Chore**: Dependency updates, config tweaks, file renames
- **Docs**: Main docs, SWE Agent rules, tutorials, examples, READMEs
- **CI/CD**: GitHub Actions, packaging, release tooling

## Requirements

- Python ≥3.10
- [uv](https://docs.astral.sh/uv/) ≥0.7.2

## Contribution Process

1. **Fork and clone the repository**
   - Fork the [mthds repository](https://github.com/Pipelex/mthds)
   - Clone your fork locally

2. **Install dependencies**
   ```bash
   make install
   ```
   This will create a virtual environment and install all project dependencies using uv.

3. **Run initial checks**
   ```bash
   make check
   ```
   This runs formatting, linting, type checking (pyright, mypy, pylint), and checks for unused imports.

4. **Create a feature branch**
   - Branch format: `category/short_slug`
   - Categories: `feature`, `fix`, `refactor`, `docs`, `cicd`, or `chore`
   - Example: `feature/add-timeout-parameter` or `fix/credential-validation`

5. **Make your changes**
   - Write clean, readable code following existing patterns
   - Keep commits atomic and well-described
   - Update documentation if needed

6. **Run quality checks before submitting**
   ```bash
   make check
   ```

7. **Push to your fork**
   ```bash
   git push origin your-branch-name
   ```

8. **Open a Pull Request**
   - [Link to an existing Issue](https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue) (no `needs triage` label)
   - Fill in the PR title and description using the template
   - Mark as **Draft** until CI checks pass
   - CI tests will run automatically

9. **Code review and merge**
    - Maintainers will review your code
    - Respond to feedback if required
    - Once approved and CI passes, your contribution will be merged!

## License

* **CLA** – The first time you open a PR, the CLA-assistant bot will guide you through signing the Contributor License Agreement. The process signature uses the [CLA assistant lite](https://github.com/marketplace/actions/cla-assistant-lite).
* **Code of Conduct** – Be kind. All interactions fall under [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
