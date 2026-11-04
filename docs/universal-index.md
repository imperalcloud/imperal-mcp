# The universal index

`imperal-mcp` indexes the folder it starts in - a repository, a home folder, a folder of contracts or a mobile app -
so `search_code`, `outline`, `read_symbol` and `impact_of_change` work on whatever you keep there.

## Units

The workspace is split into units, each built in the background and refreshed on its own:

| Unit | What it is |
| :--- | :--- |
| Repository | Every git repository down to depth 4 (`~/Projects/app`, `~/Work/client/api`) |
| Collection | Every other top-level folder (`Documents`, `Desktop`, `Downloads`, ...), minus the repositories inside it |
| Root files | Files lying directly in the workspace |
| iCloud Drive | `~/Library/Mobile Documents/com~apple~CloudDocs`, only when no part of that path is a link |

Inside a unit the folder you work in is indexed first, then what changed in the last 30 days, then the rest. The first
answer comes from what is ready; `search_code` reports the build's progress until it is done. A unit that resolves
outside the workspace is never indexed.

## File kinds

| Kind | Files | What the index keeps |
| :--- | :--- | :--- |
| `code` | 20+ languages: Python, TypeScript, JavaScript, Kotlin, Java, Swift, Go, Rust, C/C++, C#, PHP, Ruby, Dart, Scala, Lua, Bash, SQL, HTML, CSS; Dockerfile, Makefile, Gemfile, ... | Symbols, imports, calls |
| `config` | `tsconfig*.json`, `jsconfig.json`, `package.json`, `pyproject.toml`, `setup.cfg` | Keys; resolution paths |
| `document` | DOCX, ODT, PDF (pages and bookmarks), legacy DOC, RTF, Markdown, reStructuredText, `.htm`, plain text; slides: PPTX, ODP, legacy PPT | Headings, pages and slides as sections, text |
| `data` | XLSX, ODS, legacy XLS, CSV/TSV, JSON, YAML, TOML, XML | Sheets and keys as sections |
| `mail` | EML, MBOX | One section per message; sender, subject, attachments |
| `image` | JPEG, PNG, HEIC, TIFF | Metadata only (Exif: when, camera) - never pixels |

`outline(path)` lists a file's sections, `read_symbol(path, "3.2 Payment terms")` (any case) or
`read_symbol(path, "L120-180")` reads one, and `search_code(query, kind="document")` keeps one kind.

## Never read

These are never opened, whatever asks for them: secrets by name (`.env*`, `id_*`, `*.pem`, `*.key`, `credentials*`,
`*.tfstate`, `.netrc`, ...), `.ssh`, `.aws`, `.gnupg`, keychains, browser profiles, password stores (`*.kdbx`,
`.password-store`), `wallet.dat`, VPN profiles, cloud and tool credential files; iCloud placeholders (opening one would download it); app packages
(`.app`, `.photoslibrary`, ...). The check ignores case and trailing dots and follows links to where they lead.

Untrusted files are read inside budgets: XML never expands entities, an Office file stays inside a document-wide budget
(200 MB unpacked), a view keeps at most 2 million characters, and a file over its kind's cap (10 MB code, 100 MB
otherwise) is listed as skipped with the reason.

## What leaves your machine

Only code and resolution configs reach your code map in the vault, as before. Documents, sheets, slides, mail and
image metadata stay in the local index on your machine.

What your agent reads with a tool - a section of a contract through `read_symbol`, like a file through `cat` - is a
step of the session, and the shell's hooks record steps in your private space (masked for secrets and personal data
first, see the README's "What leaves your machine").
