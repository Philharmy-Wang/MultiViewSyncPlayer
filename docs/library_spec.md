# MVSP Media Library — Directory Specification (v0.2)

> This document defines the canonical directory layout and metadata files for
> the MVSP media library introduced in v0.2.

## 1. Four-level directory tree

```
<library_root>/
├── library.mvsp-lib.json          # library-wide index (see §3)
├── ThreeChamber/                  # experiment name
│   ├── 2026-01-26/               # date (ISO YYYY-MM-DD)
│   │   ├── 24332/                # subject / individual
│   │   │   ├── _meta.json        # subject-level metadata (see §4)
│   │   │   ├── front-1.mp4
│   │   │   ├── back-1.mp4
│   │   │   ├── left-1.mp4
│   │   │   └── right-1.mp4
│   │   └── 24333/
│   │       ├── _meta.json
│   │       ├── front-1.mp4
│   │       └── ...
│   └── 2026-01-27/
│       └── ...
└── OpenField/
    └── ...
```

## 2. Naming constraints

| Level | Rule |
|---|---|
| **Experiment name** | Must not contain `/`, `\`, `:`, or any Windows-forbidden character (`<>:"/\|?*`). Use `library.paths.sanitize()` to clean. |
| **Date** | Must be ISO `YYYY-MM-DD`. This is enforced by using `datetime.date.isoformat()`. |
| **Subject ID** | Recommended: alphanumeric, `-`, `_`. Will be sanitized through the same `sanitize()` function. |
| **View filename** | Derived from view name + extension. Sanitized. Duplicate view names within one subject are not allowed. |

## 3. `library.mvsp-lib.json` — Library index (placeholder)

> **Note:** This file will be fully specified and implemented in **Step 5** (LibraryIndex).

Planned top-level structure:

```jsonc
{
  "version": "0.2.0",
  "library_root": "<absolute path>",
  "experiments": [
    {
      "name": "ThreeChamber",
      "dates": [
        {
          "date": "2026-01-26",
          "subjects": ["24332", "24333"]
        }
      ]
    }
  ],
  "scan_timestamp": "2026-01-26T14:30:00"
}
```

## 4. `_meta.json` — Subject-level metadata (placeholder)

> **Note:** Will be written by the importer in **Step 4** and refined there.

Planned fields:

```jsonc
{
  "subject_id": "24332",
  "experiment": "ThreeChamber",
  "date": "2026-01-26",
  "views": [
    {
      "name": "front-1",
      "direction": "front",
      "index": 1,
      "color": "#42a5f5",
      "video_path": "front-1.mp4",
      "duration_sec": 3600.0,
      "fps": 30.0
    }
  ],
  "notes": ""
}
```

## 5. Relationship with `.mvsp.json` session files

- A session file (`.mvsp.json`) is **standalone by default** — it can be opened without any library.
- A session **may reference** a library subject via a `library_ref` field (added in Step 8):
  ```jsonc
  {
    "library_ref": {
      "library_root": "K:/MVSP_Library",
      "experiment": "ThreeChamber",
      "date": "2026-01-26",
      "subject_id": "24332"
    }
  }
  ```
- When a session has a `library_ref`, the UI can offer "reload from library" to re-import the latest files.

## 6. Relationship with `project_template.py`

The two systems are **complementary**, not competing:

| Feature | `project_template` | `library` |
|---|---|---|
| **Purpose** | Scan unstructured directories by regex naming patterns | Manage normalized, metadata-rich storage |
| **Input** | Any folder with video files | Standardized directory tree |
| **Output** | `GroupEntry` list (file groups) | Full Experiment/Subject/View model |
| **Persistence** | `.json` template files | `library.mvsp-lib.json` + `_meta.json` |
| **Workflow** | Quick one-off scan → load | Import once → browse → double-click to load |

Users may start with `project_template` for ad-hoc analysis, then use the library import wizard to organize files into the canonical structure for long-term projects.
