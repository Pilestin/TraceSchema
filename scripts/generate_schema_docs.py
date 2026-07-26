#!/usr/bin/env python3
"""Generate diff report for two selected schema files."""

import difflib
import re
from pathlib import Path

from jinja2 import Environment
from lxml import etree

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schema"
OUTPUT_DIR = REPO_ROOT / "version_diff"

XSD_NS = "http://www.w3.org/2001/XMLSchema"
NS = {"xs": XSD_NS}
SCHEMA_FILE_PATTERN = re.compile(r"^trace_schema_v(?P<version>\d+(?:\.\d+)*)\.xsd$")

# Set only these two files to control which schema versions are compared.
LEFT_SCHEMA_FILE = "trace_schema_v2.2.xsd"
RIGHT_SCHEMA_FILE = "trace_schema_v2.3.xsd"

# If False, only diff and index pages are generated.
GENERATE_SCHEMA_DOC_PAGES = False


def version_key(version: str) -> tuple[int, ...]:
        return tuple(int(part) for part in version.split("."))


def slugify(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
        return slug or "item"


def get_doc(elem: etree._Element) -> str:
        doc = elem.find("xs:annotation/xs:documentation", namespaces=NS)
        if doc is None:
                return ""
        text = "".join(doc.itertext()).strip()
        return " ".join(text.split())


def occurs_text(min_occurs: str, max_occurs: str) -> str:
        return f"{min_occurs}..{max_occurs}"


def discover_schemas() -> list[dict]:
        schemas: list[dict] = []
        for xsd_path in SCHEMA_DIR.glob("trace_schema_v*.xsd"):
                match = SCHEMA_FILE_PATTERN.match(xsd_path.name)
                if not match:
                        continue
                version = match.group("version")
                schemas.append(
                        {
                                "version": version,
                                "version_key": version_key(version),
                                "file_path": xsd_path,
                                "file_name": xsd_path.name,
                                "schema_doc_file": f"schema-v{version}.html",
                        }
                )
        schemas.sort(key=lambda item: item["version_key"])
        return schemas

def parse_version_from_filename(file_name: str) -> str:
        match = SCHEMA_FILE_PATTERN.match(file_name)
        if match:
                return match.group("version")

        stem = Path(file_name).stem
        stem = stem.replace("trace_schema_", "")
        return stem


def create_schema_meta(file_name: str) -> dict:
        version = parse_version_from_filename(file_name)
        safe_version = re.sub(r"[^a-zA-Z0-9_.-]+", "-", version)
        return {
                "version": version,
                "file_path": SCHEMA_DIR / file_name,
                "file_name": file_name,
                "schema_doc_file": f"schema-v{safe_version}.html",
        }


def selected_schemas() -> tuple[dict, dict]:
        left = create_schema_meta(LEFT_SCHEMA_FILE)
        right = create_schema_meta(RIGHT_SCHEMA_FILE)

        if left["file_name"] == right["file_name"]:
                raise ValueError("LEFT_SCHEMA_FILE and RIGHT_SCHEMA_FILE must be different files.")

        missing = [
                schema["file_name"]
                for schema in (left, right)
                if not schema["file_path"].exists()
        ]
        if missing:
                joined = ", ".join(missing)
                raise FileNotFoundError(f"Schema file not found in schema/: {joined}")

        return left, right


def parse_xsd(xsd_path: Path) -> dict:
        parser = etree.XMLParser(remove_comments=True)
        root = etree.parse(str(xsd_path), parser).getroot()

        root_elements = []
        for element in root.findall("xs:element", namespaces=NS):
                min_occurs = element.get("minOccurs", "1")
                max_occurs = element.get("maxOccurs", "1")
                root_elements.append(
                        {
                                "name": element.get("name", ""),
                                "type": element.get("type", "(inline)"),
                                "required": min_occurs != "0",
                                "occurs": occurs_text(min_occurs, max_occurs),
                                "doc": get_doc(element),
                        }
                )

        complex_types = []
        for ct in root.findall("xs:complexType", namespaces=NS):
                elements = []
                attributes = []
                child_elements = ct.xpath(
                        "./xs:sequence/xs:element"
                        " | ./xs:choice/xs:element"
                        " | ./xs:all/xs:element"
                        " | ./xs:complexContent/xs:extension/xs:sequence/xs:element"
                        " | ./xs:complexContent/xs:extension/xs:choice/xs:element",
                        namespaces=NS,
                )
                for element in child_elements:
                        min_occurs = element.get("minOccurs", "1")
                        max_occurs = element.get("maxOccurs", "1")
                        elements.append(
                                {
                                        "name": element.get("name", ""),
                                        "type": element.get("type", "(inline)"),
                                        "required": min_occurs != "0",
                                        "min_occurs": min_occurs,
                                        "max_occurs": max_occurs,
                                        "occurs": occurs_text(min_occurs, max_occurs),
                                        "doc": get_doc(element),
                                }
                        )

                child_attrs = ct.xpath(
                        "./xs:attribute | ./xs:complexContent/xs:extension/xs:attribute",
                        namespaces=NS,
                )
                for attr in child_attrs:
                        attributes.append(
                                {
                                        "name": attr.get("name", ""),
                                        "type": attr.get("type", "xs:string"),
                                        "required": attr.get("use", "optional") == "required",
                                        "doc": get_doc(attr),
                                }
                        )

                complex_types.append(
                        {
                                "name": ct.get("name", ""),
                                "slug": slugify(ct.get("name", "")),
                                "doc": get_doc(ct),
                                "elements": elements,
                                "attributes": attributes,
                        }
                )

        simple_types = []
        for st in root.findall("xs:simpleType", namespaces=NS):
                enum_values = [
                        enum.get("value", "") for enum in st.findall(".//xs:enumeration", namespaces=NS)
                ]
                simple_types.append(
                        {
                                "name": st.get("name", ""),
                                "slug": slugify(st.get("name", "")),
                                "doc": get_doc(st),
                                "enum_values": enum_values,
                        }
                )

        return {
                "schema_version": root.get("version", ""),
                "root_elements": root_elements,
                "complex_types": complex_types,
                "simple_types": simple_types,
                "raw_xsd": xsd_path.read_text(encoding="utf-8"),
        }


def complex_type_signature(ctype: dict) -> dict:
        elements = {
                (
                        el["name"],
                        el["type"],
                        el["min_occurs"],
                        el["max_occurs"],
                )
                for el in ctype["elements"]
        }
        attributes = {
                (attr["name"], attr["type"], attr["required"])
                for attr in ctype["attributes"]
        }
        return {"elements": elements, "attributes": attributes}


def compute_type_diffs(left_schema: dict, right_schema: dict) -> dict:
        left_types = {ct["name"]: ct for ct in left_schema["complex_types"]}
        right_types = {ct["name"]: ct for ct in right_schema["complex_types"]}

        left_names = set(left_types)
        right_names = set(right_types)

        changed = []
        for name in sorted(left_names & right_names):
                left_sig = complex_type_signature(left_types[name])
                right_sig = complex_type_signature(right_types[name])
                if left_sig == right_sig:
                        continue

                changed.append(
                        {
                                "name": name,
                                "elements_added": sorted(
                                        right_sig["elements"] - left_sig["elements"],
                                        key=lambda item: item[0],
                                ),
                                "elements_removed": sorted(
                                        left_sig["elements"] - right_sig["elements"],
                                        key=lambda item: item[0],
                                ),
                                "attributes_added": sorted(
                                        right_sig["attributes"] - left_sig["attributes"],
                                        key=lambda item: item[0],
                                ),
                                "attributes_removed": sorted(
                                        left_sig["attributes"] - right_sig["attributes"],
                                        key=lambda item: item[0],
                                ),
                        }
                )

        return {
                "added": sorted(right_names - left_names),
                "removed": sorted(left_names - right_names),
                "changed": changed,
                "common_count": len(left_names & right_names),
        }


def make_unified_diff(left_file: Path, right_file: Path) -> str:
        left_lines = left_file.read_text(encoding="utf-8").splitlines(keepends=True)
        right_lines = right_file.read_text(encoding="utf-8").splitlines(keepends=True)
        diff_lines = difflib.unified_diff(
                left_lines,
                right_lines,
                fromfile=left_file.name,
                tofile=right_file.name,
                n=3,
        )
        return "".join(diff_lines)


ENV = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)

DOC_TEMPLATE = ENV.from_string(
        """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Schema v{{ schema.version }} - TraceSchema Docs</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
    <link rel="stylesheet" href="../site/schema-shared.css" />
</head>
<body>
    <nav>
        <a href="../index.html" class="nav-brand">
            <div class="brand-icon"><svg viewBox="0 0 24 24"><path d="M13 3L4 14h8l-1 7 9-11h-8z" /></svg></div>
            TraceSchema
        </a>
        <div class="nav-right">
            <ul class="nav-links">
                <li><a href="../index.html">Home</a></li>
                {% for item in schema_nav %}
                <li><a href="{{ item.href }}" class="{{ 'active' if item.active else '' }}">{{ item.label }}</a></li>
                {% endfor %}
                <li><a href="index.html">Diff Index</a></li>
            </ul>
            <button class="theme-btn" title="Toggle theme" onclick="toggleTheme()">
                <svg id="icon-sun" viewBox="0 0 24 24" style="display:none"><path d="M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0 2a1 1 0 0 1 1 1v1a1 1 0 0 1-2 0v-1a1 1 0 0 1 1-1zm0-16a1 1 0 0 1 1 1v1a1 1 0 0 1-2 0V4a1 1 0 0 1 1-1zm9 8a1 1 0 0 1 0 2h-1a1 1 0 0 1 0-2h1zM4 12a1 1 0 0 1 0 2H3a1 1 0 0 1 0-2h1z"/></svg>
                <svg id="icon-moon" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" /></svg>
            </button>
        </div>
    </nav>

    <div class="page-wrap">
        <aside class="sidebar">
            <div class="sidebar-section">
                <div class="sidebar-label">Root Elements</div>
                {% for el in parsed.root_elements %}
                <a href="#root-{{ el.name | lower }}" class="sidebar-link">{{ el.name }}</a>
                {% endfor %}
            </div>
            <div class="sidebar-section">
                <div class="sidebar-label">Complex Types</div>
                {% for ctype in parsed.complex_types %}
                <a href="#type-{{ ctype.slug }}" class="sidebar-link">{{ ctype.name }}</a>
                {% endfor %}
            </div>
            {% if parsed.simple_types %}
            <div class="sidebar-section">
                <div class="sidebar-label">Simple Types</div>
                {% for stype in parsed.simple_types %}
                <a href="#simple-{{ stype.slug }}" class="sidebar-link">{{ stype.name }}</a>
                {% endfor %}
            </div>
            {% endif %}
            <div class="sidebar-section">
                <div class="sidebar-label">Source</div>
                <a href="#raw-xsd" class="sidebar-link">Raw XSD</a>
            </div>
        </aside>

        <main>
            <div class="page-header">
                <div class="version-tag {{ 'green' if is_latest else '' }}">v{{ schema.version }}{{ ' - Latest' if is_latest else '' }}</div>
                <h1 class="page-title">Schema v{{ schema.version }} Documentation</h1>
                <p class="page-desc">Generated from <code>{{ schema.file_name }}</code>. Schema attribute version: <code>{{ parsed.schema_version or 'N/A' }}</code>.</p>
            </div>

            <div class="actions-bar">
                <a href="../schema/{{ schema.file_name }}" class="btn btn-primary" download>Download XSD</a>
                <a href="index.html" class="btn btn-secondary">Open Diff Index</a>
            </div>

            <div class="doc-section">
                <h2 class="section-title">Root Elements</h2>
                {% for el in parsed.root_elements %}
                <div class="type-card" id="root-{{ el.name | lower }}">
                    <div class="type-card-header" onclick="toggleCard(this)">
                        <span class="type-name">{{ el.name }}</span>
                        <div class="header-right">
                            <span class="type-kind kind-element">root element</span>
                            <span class="chevron">▶</span>
                        </div>
                    </div>
                    <div class="type-card-body">
                        {% if el.doc %}<div class="type-doc">{{ el.doc }}</div>{% endif %}
                        <table class="mini-table">
                            <thead>
                                <tr><th>Type</th><th>Occurs</th><th>Required</th></tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><code>{{ el.type }}</code></td>
                                    <td class="occur">{{ el.occurs }}</td>
                                    <td><span class="req-badge {{ 'req-yes' if el.required else 'req-no' }}">{{ 'required' if el.required else 'optional' }}</span></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
                {% endfor %}
            </div>

            <div class="doc-section">
                <h2 class="section-title">Complex Types</h2>
                {% for ctype in parsed.complex_types %}
                <div class="type-card" id="type-{{ ctype.slug }}">
                    <div class="type-card-header" onclick="toggleCard(this)">
                        <span class="type-name">{{ ctype.name }}</span>
                        <div class="header-right">
                            <span class="type-kind kind-complex">complexType</span>
                            <span class="chevron">▶</span>
                        </div>
                    </div>
                    <div class="type-card-body">
                        {% if ctype.doc %}<div class="type-doc">{{ ctype.doc }}</div>{% endif %}
                        {% if ctype.elements %}
                        <p class="mini-label">Child Elements</p>
                        <table class="mini-table">
                            <thead>
                                <tr><th>Element</th><th>Type</th><th>Occurs</th><th>Description</th></tr>
                            </thead>
                            <tbody>
                                {% for el in ctype.elements %}
                                <tr>
                                    <td><code>{{ el.name }}</code></td>
                                    <td><code>{{ el.type }}</code></td>
                                    <td class="occur">{{ el.occurs }}</td>
                                    <td>{{ el.doc }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                        {% endif %}
                        {% if ctype.attributes %}
                        <p class="mini-label">Attributes</p>
                        <table class="mini-table">
                            <thead>
                                <tr><th>Attribute</th><th>Type</th><th>Required</th><th>Description</th></tr>
                            </thead>
                            <tbody>
                                {% for attr in ctype.attributes %}
                                <tr>
                                    <td><code>{{ attr.name }}</code></td>
                                    <td><code>{{ attr.type }}</code></td>
                                    <td><span class="req-badge {{ 'req-yes' if attr.required else 'req-no' }}">{{ 'required' if attr.required else 'optional' }}</span></td>
                                    <td>{{ attr.doc }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>

            {% if parsed.simple_types %}
            <div class="doc-section">
                <h2 class="section-title">Simple Types</h2>
                {% for stype in parsed.simple_types %}
                <div class="type-card" id="simple-{{ stype.slug }}">
                    <div class="type-card-header" onclick="toggleCard(this)">
                        <span class="type-name">{{ stype.name }}</span>
                        <div class="header-right">
                            <span class="type-kind kind-enum">simpleType</span>
                            <span class="chevron">▶</span>
                        </div>
                    </div>
                    <div class="type-card-body">
                        {% if stype.doc %}<div class="type-doc">{{ stype.doc }}</div>{% endif %}
                        {% if stype.enum_values %}
                        <p class="mini-label">Enumeration Values</p>
                        <table class="mini-table">
                            <thead>
                                <tr><th>Value</th></tr>
                            </thead>
                            <tbody>
                                {% for value in stype.enum_values %}
                                <tr><td><code>{{ value }}</code></td></tr>
                                {% endfor %}
                            </tbody>
                        </table>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>
            {% endif %}

            <div class="doc-section" id="raw-xsd">
                <h2 class="section-title">Raw XSD</h2>
                <div class="raw-header"><span class="raw-filename">{{ schema.file_name }}</span></div>
                <div class="code-wrap"><pre>{{ parsed.raw_xsd }}</pre></div>
            </div>
        </main>
    </div>

    <footer>Generated automatically from schema files.</footer>

    <script>
        function toggleCard(header) {
            const body = header.nextElementSibling;
            const chevron = header.querySelector('.chevron');
            const isOpen = body.style.display === 'block';
            body.style.display = isOpen ? 'none' : 'block';
            chevron.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(90deg)';
        }

        function toggleTheme() {
            const html = document.documentElement;
            const isDark = html.getAttribute('data-theme') === 'dark';
            html.setAttribute('data-theme', isDark ? 'light' : 'dark');
            localStorage.setItem('schema-theme', isDark ? 'light' : 'dark');
            refreshThemeIcons();
        }

        function refreshThemeIcons() {
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            document.getElementById('icon-moon').style.display = isDark ? 'block' : 'none';
            document.getElementById('icon-sun').style.display = isDark ? 'none' : 'block';
        }

        (function initTheme() {
            const savedTheme = localStorage.getItem('schema-theme');
            if (savedTheme) {
                document.documentElement.setAttribute('data-theme', savedTheme);
            }
            refreshThemeIcons();
        })();
    </script>
</body>
</html>
"""
)

DIFF_TEMPLATE = ENV.from_string(
        """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Schema Diff v{{ left.version }} to v{{ right.version }} - TraceSchema Docs</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
    <link rel="stylesheet" href="../site/schema-shared.css" />
    <style>
        .diff-page { position: relative; z-index: 1; max-width: 1200px; margin: 0 auto; padding: 36px 2rem 80px; }
        .diff-stats { display: flex; gap: 10px; margin: 10px 0 24px; flex-wrap: wrap; }
        .diff-stat { display: inline-flex; padding: 6px 12px; border-radius: 6px; font-size: 0.8rem; font-weight: 700; }
        .stat-added { background: rgba(63,185,80,0.1); color: var(--green); border: 1px solid rgba(63,185,80,0.2); }
        .stat-removed { background: rgba(248,81,73,0.1); color: var(--red); border: 1px solid rgba(248,81,73,0.2); }
        .stat-changed { background: rgba(88,166,255,0.1); color: var(--accent); border: 1px solid rgba(88,166,255,0.2); }
        .list-wrap { display: grid; gap: 10px; margin-bottom: 22px; }
        .chip { display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 999px; font-size: 0.72rem; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
        .chip-added { background: rgba(63,185,80,0.12); color: var(--green); }
        .chip-removed { background: rgba(248,81,73,0.12); color: var(--red); }
        .chip-changed { background: rgba(88,166,255,0.12); color: var(--accent); }
        .code-wrap pre { margin: 0; font-family: 'JetBrains Mono', monospace; font-size: 0.78rem; line-height: 1.55; }
    </style>
</head>
<body>
    <nav>
        <a href="../index.html" class="nav-brand">
            <div class="brand-icon"><svg viewBox="0 0 24 24"><path d="M13 3L4 14h8l-1 7 9-11h-8z" /></svg></div>
            TraceSchema
        </a>
        <div class="nav-right">
            <ul class="nav-links">
                <li><a href="../index.html">Home</a></li>
                {% for item in schema_nav %}
                <li><a href="{{ item.href }}">{{ item.label }}</a></li>
                {% endfor %}
                <li><a href="index.html" class="active">Diff Index</a></li>
            </ul>
            <button class="theme-btn" title="Toggle theme" onclick="toggleTheme()">
                <svg id="icon-sun" viewBox="0 0 24 24" style="display:none"><path d="M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0 2a1 1 0 0 1 1 1v1a1 1 0 0 1-2 0v-1a1 1 0 0 1 1-1zm0-16a1 1 0 0 1 1 1v1a1 1 0 0 1-2 0V4a1 1 0 0 1 1-1zm9 8a1 1 0 0 1 0 2h-1a1 1 0 0 1 0-2h1zM4 12a1 1 0 0 1 0 2H3a1 1 0 0 1 0-2h1z"/></svg>
                <svg id="icon-moon" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" /></svg>
            </button>
        </div>
    </nav>

    <div class="diff-page">
        <div class="page-header">
            <div class="version-tag green">Diff Report</div>
            <h1 class="page-title">Schema v{{ left.version }} to v{{ right.version }}</h1>
            <p class="page-desc">Comparison between <code>{{ left.file_name }}</code> and <code>{{ right.file_name }}</code>.</p>
        </div>

        <div class="actions-bar">
            {% if include_schema_docs %}
            <a href="{{ left.schema_doc_file }}" class="btn btn-secondary">Open v{{ left.version }} Docs</a>
            <a href="{{ right.schema_doc_file }}" class="btn btn-secondary">Open v{{ right.version }} Docs</a>
            {% endif %}
            <a href="index.html" class="btn btn-primary">Back to Diff Index</a>
        </div>

        <div class="diff-stats">
            <span class="diff-stat stat-added">Added Types: {{ diff.added | length }}</span>
            <span class="diff-stat stat-removed">Removed Types: {{ diff.removed | length }}</span>
            <span class="diff-stat stat-changed">Changed Types: {{ diff.changed | length }}</span>
            <span class="diff-stat stat-changed">Common Types: {{ diff.common_count }}</span>
        </div>

        <div class="doc-section">
            <h2 class="section-title">Added and Removed Types</h2>
            <div class="list-wrap">
                <div>
                    <p class="mini-label">Added</p>
                    {% if diff.added %}
                        {% for name in diff.added %}<span class="chip chip-added">{{ name }}</span> {% endfor %}
                    {% else %}
                        <p class="page-desc">No new complex types.</p>
                    {% endif %}
                </div>
                <div>
                    <p class="mini-label">Removed</p>
                    {% if diff.removed %}
                        {% for name in diff.removed %}<span class="chip chip-removed">{{ name }}</span> {% endfor %}
                    {% else %}
                        <p class="page-desc">No removed complex types.</p>
                    {% endif %}
                </div>
            </div>
        </div>

        <div class="doc-section">
            <h2 class="section-title">Changed Type Details</h2>
            {% if diff.changed %}
                {% for item in diff.changed %}
                <div class="type-card">
                    <div class="type-card-header" onclick="toggleCard(this)">
                        <span class="type-name">{{ item.name }}</span>
                        <div class="header-right">
                            <span class="type-kind kind-new">CHANGED</span>
                            <span class="chevron">▶</span>
                        </div>
                    </div>
                    <div class="type-card-body">
                        <p class="mini-label">Elements Added</p>
                        {% if item.elements_added %}
                        <table class="mini-table">
                            <thead><tr><th>Name</th><th>Type</th><th>Occurs</th></tr></thead>
                            <tbody>
                            {% for el in item.elements_added %}
                                <tr><td><code>{{ el[0] }}</code></td><td><code>{{ el[1] }}</code></td><td class="occur">{{ el[2] }}..{{ el[3] }}</td></tr>
                            {% endfor %}
                            </tbody>
                        </table>
                        {% else %}<p class="page-desc">No added elements.</p>{% endif %}

                        <p class="mini-label">Elements Removed</p>
                        {% if item.elements_removed %}
                        <table class="mini-table">
                            <thead><tr><th>Name</th><th>Type</th><th>Occurs</th></tr></thead>
                            <tbody>
                            {% for el in item.elements_removed %}
                                <tr><td><code>{{ el[0] }}</code></td><td><code>{{ el[1] }}</code></td><td class="occur">{{ el[2] }}..{{ el[3] }}</td></tr>
                            {% endfor %}
                            </tbody>
                        </table>
                        {% else %}<p class="page-desc">No removed elements.</p>{% endif %}

                        <p class="mini-label">Attributes Added</p>
                        {% if item.attributes_added %}
                        <table class="mini-table">
                            <thead><tr><th>Name</th><th>Type</th><th>Required</th></tr></thead>
                            <tbody>
                            {% for attr in item.attributes_added %}
                                <tr><td><code>{{ attr[0] }}</code></td><td><code>{{ attr[1] }}</code></td><td>{{ 'yes' if attr[2] else 'no' }}</td></tr>
                            {% endfor %}
                            </tbody>
                        </table>
                        {% else %}<p class="page-desc">No added attributes.</p>{% endif %}

                        <p class="mini-label">Attributes Removed</p>
                        {% if item.attributes_removed %}
                        <table class="mini-table">
                            <thead><tr><th>Name</th><th>Type</th><th>Required</th></tr></thead>
                            <tbody>
                            {% for attr in item.attributes_removed %}
                                <tr><td><code>{{ attr[0] }}</code></td><td><code>{{ attr[1] }}</code></td><td>{{ 'yes' if attr[2] else 'no' }}</td></tr>
                            {% endfor %}
                            </tbody>
                        </table>
                        {% else %}<p class="page-desc">No removed attributes.</p>{% endif %}
                    </div>
                </div>
                {% endfor %}
            {% else %}
            <p class="page-desc">No changed complex types.</p>
            {% endif %}
        </div>

        <div class="doc-section">
            <h2 class="section-title">Unified Text Diff</h2>
            <div class="code-wrap"><pre>{{ unified_diff }}</pre></div>
        </div>
    </div>

    <footer>Generated automatically from schema files.</footer>

    <script>
        function toggleCard(header) {
            const body = header.nextElementSibling;
            const chevron = header.querySelector('.chevron');
            const isOpen = body.style.display === 'block';
            body.style.display = isOpen ? 'none' : 'block';
            chevron.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(90deg)';
        }

        function toggleTheme() {
            const html = document.documentElement;
            const isDark = html.getAttribute('data-theme') === 'dark';
            html.setAttribute('data-theme', isDark ? 'light' : 'dark');
            localStorage.setItem('schema-theme', isDark ? 'light' : 'dark');
            refreshThemeIcons();
        }

        function refreshThemeIcons() {
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            document.getElementById('icon-moon').style.display = isDark ? 'block' : 'none';
            document.getElementById('icon-sun').style.display = isDark ? 'none' : 'block';
        }

        (function initTheme() {
            const savedTheme = localStorage.getItem('schema-theme');
            if (savedTheme) {
                document.documentElement.setAttribute('data-theme', savedTheme);
            }
            refreshThemeIcons();
        })();
    </script>
</body>
</html>
"""
)

INDEX_TEMPLATE = ENV.from_string(
        """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Schema Diff Index - TraceSchema Docs</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
    <link rel="stylesheet" href="../site/schema-shared.css" />
    <style>
        .index-wrap { position: relative; z-index: 1; max-width: 980px; margin: 0 auto; padding: 36px 2rem 80px; }
        .list-grid { display: grid; gap: 10px; }
        .list-item { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
        .list-item a { text-decoration: none; }
    </style>
</head>
<body>
    <nav>
        <a href="../index.html" class="nav-brand">
            <div class="brand-icon"><svg viewBox="0 0 24 24"><path d="M13 3L4 14h8l-1 7 9-11h-8z" /></svg></div>
            TraceSchema
        </a>
        <div class="nav-right">
            <ul class="nav-links">
                <li><a href="../index.html">Home</a></li>
                <li><a href="index.html" class="active">Diff Index</a></li>
            </ul>
            <button class="theme-btn" title="Toggle theme" onclick="toggleTheme()">
                <svg id="icon-sun" viewBox="0 0 24 24" style="display:none"><path d="M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0 2a1 1 0 0 1 1 1v1a1 1 0 0 1-2 0v-1a1 1 0 0 1 1-1zm0-16a1 1 0 0 1 1 1v1a1 1 0 0 1-2 0V4a1 1 0 0 1 1-1zm9 8a1 1 0 0 1 0 2h-1a1 1 0 0 1 0-2h1zM4 12a1 1 0 0 1 0 2H3a1 1 0 0 1 0-2h1z"/></svg>
                <svg id="icon-moon" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" /></svg>
            </button>
        </div>
    </nav>

    <div class="index-wrap">
        <div class="page-header">
            <div class="version-tag green">Auto Generated</div>
            <h1 class="page-title">Schema Docs and Diff Index</h1>
            <p class="page-desc">All pages generated from files in <code>schema/</code>.</p>
        </div>

        {% if include_schema_docs %}
        <div class="doc-section">
            <h2 class="section-title">Schema Documentation Pages</h2>
            <div class="changelog-grid">
                {% for schema in schemas %}
                <div class="cl-card list-item">
                    <div>
                        <h4>Schema v{{ schema.version }}</h4>
                        <p>Source: <code>{{ schema.file_name }}</code></p>
                    </div>
                    <a href="{{ schema.schema_doc_file }}" class="btn btn-secondary">Open Docs</a>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        <div class="doc-section">
            <h2 class="section-title">Pairwise Diff Reports</h2>
            <div class="changelog-grid">
                {% if diff_pages %}
                    {% for diff in diff_pages %}
                    <div class="cl-card list-item">
                        <div>
                            <h4>v{{ diff.left.version }} to v{{ diff.right.version }}</h4>
                            <p><code>{{ diff.left.file_name }}</code> to <code>{{ diff.right.file_name }}</code></p>
                        </div>
                        <a href="{{ diff.file_name }}" class="btn btn-primary">Open Diff</a>
                    </div>
                    {% endfor %}
                {% else %}
                    <p class="page-desc">At least two schema files are required to generate a diff.</p>
                {% endif %}
            </div>
        </div>
    </div>

    <footer>Generated automatically from schema files.</footer>

    <script>
        function toggleTheme() {
            const html = document.documentElement;
            const isDark = html.getAttribute('data-theme') === 'dark';
            html.setAttribute('data-theme', isDark ? 'light' : 'dark');
            localStorage.setItem('schema-theme', isDark ? 'light' : 'dark');
            refreshThemeIcons();
        }

        function refreshThemeIcons() {
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            document.getElementById('icon-moon').style.display = isDark ? 'block' : 'none';
            document.getElementById('icon-sun').style.display = isDark ? 'none' : 'block';
        }

        (function initTheme() {
            const savedTheme = localStorage.getItem('schema-theme');
            if (savedTheme) {
                document.documentElement.setAttribute('data-theme', savedTheme);
            }
            refreshThemeIcons();
        })();
    </script>
</body>
</html>
"""
)


def generate_docs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    left_schema, right_schema = selected_schemas()
    schemas = [left_schema, right_schema]

    parsed_by_file: dict[str, dict] = {}
    for schema in schemas:
        parsed_by_file[schema["file_name"]] = parse_xsd(schema["file_path"])

    latest_version = right_schema["version"]
    schema_nav = [
        {
            "label": f"v{schema['version']} Docs",
            "href": schema["schema_doc_file"],
            "active": False,
        }
        for schema in schemas
    ] if GENERATE_SCHEMA_DOC_PAGES else []

    if GENERATE_SCHEMA_DOC_PAGES:
        for schema in schemas:
            parsed = parsed_by_file[schema["file_name"]]
            nav_for_page = [dict(item) for item in schema_nav]
            for item in nav_for_page:
                item["active"] = item["href"] == schema["schema_doc_file"]

            out_html = DOC_TEMPLATE.render(
                schema=schema,
                parsed=parsed,
                schema_nav=nav_for_page,
                is_latest=schema["version"] == latest_version,
            )
            out_path = OUTPUT_DIR / schema["schema_doc_file"]
            out_path.write_text(out_html, encoding="utf-8")
            print(f"Generated: {out_path}")

    diff_file_name = f"diff-v{left_schema['version']}-to-v{right_schema['version']}.html"
    diff_data = compute_type_diffs(
        parsed_by_file[left_schema["file_name"]],
        parsed_by_file[right_schema["file_name"]],
    )
    unified_diff = make_unified_diff(left_schema["file_path"], right_schema["file_path"])

    diff_html = DIFF_TEMPLATE.render(
        left=left_schema,
        right=right_schema,
        diff=diff_data,
        unified_diff=unified_diff,
        schema_nav=schema_nav,
        include_schema_docs=GENERATE_SCHEMA_DOC_PAGES,
    )
    diff_path = OUTPUT_DIR / diff_file_name
    diff_path.write_text(diff_html, encoding="utf-8")
    print(f"Generated: {diff_path}")

    diff_pages = [{"left": left_schema, "right": right_schema, "file_name": diff_file_name}]

    index_html = INDEX_TEMPLATE.render(
        schemas=schemas,
        diff_pages=diff_pages,
        include_schema_docs=GENERATE_SCHEMA_DOC_PAGES,
    )
    index_path = OUTPUT_DIR / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    print(f"Generated: {index_path}")


if __name__ == "__main__":
    generate_docs()
