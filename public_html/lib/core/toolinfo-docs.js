// SPDX-License-Identifier: GPL-3.0-or-later

export const TOOLINFO_SCHEMA_VERSION = "/toolinfo/1.2.2";
export const TOOLINFO_SCHEMA_URL =
	"https://gerrit.wikimedia.org/r/plugins/gitiles/wikimedia/toolhub/+/refs/heads/main/jsonschema/toolinfo/current.yaml";
export const TOOLINFO_DATA_MODEL_URL = "https://meta.wikimedia.org/wiki/Toolhub/Data_model#Toolinfo_schema";
export const TOOLINFO_TOOL_TYPES = [
	"",
	"web app",
	"desktop app",
	"bot",
	"gadget",
	"user script",
	"command line tool",
	"coding framework",
	"lua module",
	"template",
	"other"
];

export const TOOLINFO_EXAMPLE_JSON = `{
  "_schema": "${TOOLINFO_SCHEMA_VERSION}",
  "name": "my-example-tool",
  "title": "My Example Tool",
  "description": "Helps Wikimedians inspect and improve example data.",
  "url": "https://example.org/my-example-tool",
  "author": [
    {
      "name": "Ada Lovelace",
      "wiki_username": "Ada Lovelace",
      "developer_username": "ada"
    }
  ],
  "repository": "https://example.org/my-example-tool/source",
  "license": "GPL-3.0-or-later",
  "tool_type": "web app",
  "for_wikis": [
    "www.wikidata.org"
  ],
  "available_ui_languages": [
    "en"
  ]
}`;
