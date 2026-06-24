# Contributing to Varuna360 Core

Thank you for your interest in improving Varuna360 Core.

## Repository model

This repository is a **read-only public mirror** of an internal canonical
codebase. All development happens in a private repository and is released
to this mirror in batched, verified syncs. That means:

- **Pull requests are not accepted at this time.** The mirror's commit
  history is produced by an automated release pipeline; accepting PRs
  directly would desynchronize the two repositories.
- **Direct pushes to this mirror are disabled** for everyone except the
  release pipeline.

We plan to revisit this policy once the project has stabilized.

## How to report a bug

1. Search [existing issues](https://github.com/astrologielorris/varuna360-core/issues)
   to see if your problem has already been reported.
2. If not, open a new issue. Please include:
   - Your operating system and Python version
   - Steps to reproduce
   - Expected vs. actual behavior
   - Any stack traces or screenshots (with personal data redacted)

## How to propose a fix

Since direct PRs are not accepted, please:

1. Open an issue describing the bug or feature.
2. If you have a patch, attach it as a **unified diff**
   (`git diff > fix.patch`) or a **`git format-patch`** output.
3. Include a brief explanation of the change and why it is needed.

If the patch is accepted, it will be applied to the internal repository
and will appear in this mirror on the next sync. The contributor will be
credited in the commit message unless they request otherwise.

## Code of conduct

Be kind, be technical, and keep discussions focused on the code. Personal
attacks, discrimination, and off-topic politicking will get your comments
deleted and your account blocked.

## License

By contributing a patch to Varuna360 Core, you agree that your contribution
is licensed under the same AGPL v3.0 license as the rest of the project.
