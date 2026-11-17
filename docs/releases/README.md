# Release notes

One file per release: `docs/releases/<version>.md`, where `<version>` is the version exactly as
`pyproject.toml` declares it, without the leading `v`. The file is committed **before** the tag,
because the `Release` workflow publishes it verbatim and refuses to run when it is missing.

Why the notes are stored here instead of being typed into `gh release create --notes` or generated
from commit subjects:

- **Reproducible.** The same tag always produces the same notes. `--generate-notes` groups commits
  by category and title, which is not the same document a human curates: the 0.4.1 notes explain
  the root cause of each fix and list the known limitations per release, and no generator produces
  that from commit subjects.
- **Reviewable.** Curated notes reach `main` through a pull request like any other change, instead
  of appearing in the release dialog minutes before publication.
- **Not gitignored.** The internal planning material under `odd/` is not published; notes kept
  there were lost the moment the working tree was cleaned.

## Adding a release

1. `chore(release): bump version to X.Y.Z` — update `pyproject.toml` and anything else that carries
   the version.
2. Write `docs/releases/X.Y.Z.md`: highlights that state the root cause, breaking changes, test and
   CI evidence, known limitations, and the artifact list.
3. Merge that pull request.
4. Tag the merged commit and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.

The workflow then builds, verifies and publishes. A `workflow_dispatch` run with `dry_run` rehearses
the same path (including the draft upload and the digest comparison) without publishing anything.

Older notes: `0.4.1.md` was recovered from the internal, gitignored working file so the shipped
release has its notes in the repository too.
