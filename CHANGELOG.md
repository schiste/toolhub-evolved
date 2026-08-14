# Changelog

All notable Toolhub Evolved changes, grouped from the repository's Git history.
This file is generated with `npm run changelog:generate`; do not edit it by hand.

## 2026-08-14

### Features

- separate ownership metric units ([91b1192](https://github.com/schiste/toolhub-evolved/commit/91b1192fd668125851bf7a8d639bd848d68bb08a))
- project relationship identities to cards ([e7e5fbd](https://github.com/schiste/toolhub-evolved/commit/e7e5fbd052705c52a72f34222aeed3484eb7d8ae))
- compact the archive reading layout ([bf37130](https://github.com/schiste/toolhub-evolved/commit/bf37130b0ecf5126de38dd95cd69e5012de9a995))
- enforce complete concise editions ([3b7bb6d](https://github.com/schiste/toolhub-evolved/commit/3b7bb6d7b9a32128e507e7aa5229275856b040fc))
- add verified tool attribution links ([2051d6c](https://github.com/schiste/toolhub-evolved/commit/2051d6c0520465f333d5f1ef0ec252515aeebc00))
- publish historical website examples ([4205d7b](https://github.com/schiste/toolhub-evolved/commit/4205d7ba00b6c967c77e79a0dc65021845e50659))
- ship complete Toolhub Digests ([bba5e08](https://github.com/schiste/toolhub-evolved/commit/bba5e08f45be03d92e1ce7b470552f73d1e8a535))

### Fixes

- resolve remote identities outside DB sessions ([00b7f5a](https://github.com/schiste/toolhub-evolved/commit/00b7f5adb595688db788f2a52c6b11d2d26faf85))
- resume deep recent-event backlogs ([4099a90](https://github.com/schiste/toolhub-evolved/commit/4099a90804e596999ba30285921ca67a1914fa6e))
- invalidate caches from policy source ([048c0d1](https://github.com/schiste/toolhub-evolved/commit/048c0d18407b48a6259730b1e2bce27b73bae5ea))
- make LDAP maintainer evidence authoritative ([fe265a5](https://github.com/schiste/toolhub-evolved/commit/fe265a5604281eb8049e43a0c4bd3fc9bf64e3e6))
- link proven identities on every tool card ([970fe16](https://github.com/schiste/toolhub-evolved/commit/970fe1668f309711e75656e9db920310b0dfeb86))
- link owned tools to proven people ([5204e9e](https://github.com/schiste/toolhub-evolved/commit/5204e9ee983cddf0778ebcee307e5e18b3608003))
- preserve canonical account identity ([a1a3655](https://github.com/schiste/toolhub-evolved/commit/a1a365518a670efddc9d6d67277398bb2c85e05c))
- release locks before remote lookups ([842d01e](https://github.com/schiste/toolhub-evolved/commit/842d01e933dda8b928c244b9540d8db79d6b8e54))
- decouple login from identity projection ([f7862cd](https://github.com/schiste/toolhub-evolved/commit/f7862cd70620b2e40af97b64050c89751cec5dd6))
- preflight exact LiftWing selections ([2897097](https://github.com/schiste/toolhub-evolved/commit/2897097a3b0837dac79f84cd0923b2418ce0d5d9))
- widen digest render bodies ([a9823bf](https://github.com/schiste/toolhub-evolved/commit/a9823bf9a667d2655c464d5d4318213787e9e663))
- bound busy-period LiftWing prompts ([cca1c32](https://github.com/schiste/toolhub-evolved/commit/cca1c32712618203d9c7dd989f412c35605f956a))
- recover concurrent catalog maintenance ([81cd429](https://github.com/schiste/toolhub-evolved/commit/81cd429805e5eacb79e15b1cee9dc083b219cef4))
- isolate projection refresh logs ([d5eb7da](https://github.com/schiste/toolhub-evolved/commit/d5eb7da3e56c7976aaa1d8efa1b8b039276a2f46))
- bundle technical digest notes ([2e60c45](https://github.com/schiste/toolhub-evolved/commit/2e60c450055fd4e4480a87dc977581936ab3ea22))
- harden published attribution ([cc4f003](https://github.com/schiste/toolhub-evolved/commit/cc4f003df07859c6e06c137a3bd4f02266e614e5))
- use RTL-safe attribution spacing ([7127e9b](https://github.com/schiste/toolhub-evolved/commit/7127e9b282ca931468a9d7cc6b6ae71e14037ff7))
- validate verbatim evidence excerpts ([0f74dde](https://github.com/schiste/toolhub-evolved/commit/0f74dde45b5a05ac8272acc08aa91419ed0edf7f))
- normalize unique LiftWing tool titles ([ead4a3a](https://github.com/schiste/toolhub-evolved/commit/ead4a3a2dfc7ef6d6a1d57eb4b005fa97ae5a194))
- retry work a lock conflict undid ([522cc86](https://github.com/schiste/toolhub-evolved/commit/522cc869c1f74d5a4adc6edb0dfd8d873948828b))
- reconcile the merged work with the retargeted registry pass ([4f092ac](https://github.com/schiste/toolhub-evolved/commit/4f092acb5b6702944025236e3917fdfb505bfbff))
- satisfy the type and spell gates on the new plural code ([d46248f](https://github.com/schiste/toolhub-evolved/commit/d46248f081e9c317e0d8526bd5c6cfa007650d1c))
- aim registry lookups at the labels that need them ([efc7656](https://github.com/schiste/toolhub-evolved/commit/efc765605337185f9d31aeef8980b0bb281596cc))
- count only approved reports in scanned-tool coverage ([4958850](https://github.com/schiste/toolhub-evolved/commit/495885001d98ff535baa42bb893fe4d50e58f2eb))
- tolerate case-variant curated list values ([1c119e5](https://github.com/schiste/toolhub-evolved/commit/1c119e5da2d9013cd5cc08863e9d3b01ac41a6ed))
- drop analyzer findings that carry no usable confidence ([f2c27be](https://github.com/schiste/toolhub-evolved/commit/f2c27be8a6175945e8eb1d95093f305244456919))
- re-project tools whose approved report was moderated away ([dbec50e](https://github.com/schiste/toolhub-evolved/commit/dbec50edf8950205c583f682d888f0b9f0017360))
- escape LIKE wildcards in dependency shorthand expansion ([3f4957f](https://github.com/schiste/toolhub-evolved/commit/3f4957fee45239716f0ac25bce5758e07489bfc2))
- surface unexpected handler failures as JSON-RPC errors ([bcd068a](https://github.com/schiste/toolhub-evolved/commit/bcd068a4068b1aab449b06bbd7ae333459a83079))
- treat a scalar filter argument as a one-item list ([b5d22bb](https://github.com/schiste/toolhub-evolved/commit/b5d22bb10aebcab181c17a30452ee429e3694485))

### Performance

- let the registry set the pace instead of guessing it ([797ccaf](https://github.com/schiste/toolhub-evolved/commit/797ccafb860936fcce80c76a449dee37a5af0987))
- cache coverage counts alongside facet values ([9e1ac34](https://github.com/schiste/toolhub-evolved/commit/9e1ac34e3b8eca6f4d5e37cb65c838224c504561))

### Documentation

- describe canonical people links ([ddcb990](https://github.com/schiste/toolhub-evolved/commit/ddcb9904f9b85c2db44c4bc64e3abba159fda530))
- explain authentication lock fix ([787e941](https://github.com/schiste/toolhub-evolved/commit/787e941e6a4dc82ffb0af005a1813f30cf5b4fc3))
- record attribution hardening ([05a32b5](https://github.com/schiste/toolhub-evolved/commit/05a32b5c3ee192cf8030c9f60c4b37387461c208))
- align attribution source range ([bbf98aa](https://github.com/schiste/toolhub-evolved/commit/bbf98aaa0762cb799b38e3c7d563e698afa28404))
- include RTL digest correction ([b7de77d](https://github.com/schiste/toolhub-evolved/commit/b7de77d3582e28ad7c33a91c4d4481fe3878282c))
- document attribution links ([f1b6ab5](https://github.com/schiste/toolhub-evolved/commit/f1b6ab59a24c22afad23465a0adf0eed7f4cb592))
- record evidence excerpt validation ([5a3c967](https://github.com/schiste/toolhub-evolved/commit/5a3c967b43a74cd8b6b85409bb73c1f7fb11359a))
- record LiftWing title normalization ([c718d77](https://github.com/schiste/toolhub-evolved/commit/c718d77aba8f502dc5114aea42704c3568026bae))
- record historical digest examples ([871bc75](https://github.com/schiste/toolhub-evolved/commit/871bc7581dced982d155351e39df1b76ddba2d0c))
- record stabilized browser gate ([5b76bec](https://github.com/schiste/toolhub-evolved/commit/5b76bec4a2f31c511217f27d00c5127a1b6860b9))
- record browser validation ([929fa2f](https://github.com/schiste/toolhub-evolved/commit/929fa2f0c0c21655db8071148d6d3f725deffebb))
- record digest coverage validation ([b69aab7](https://github.com/schiste/toolhub-evolved/commit/b69aab7cece8d4ec8403a6e2932bf3724523a8a9))
- announce Toolhub Digests ([087bb5d](https://github.com/schiste/toolhub-evolved/commit/087bb5d4fa5c0eb72df8f57297fe058c3bdfea3c))
- note lock-conflict retries ([0cd2a68](https://github.com/schiste/toolhub-evolved/commit/0cd2a6890cee07dc0a099e42ed1c13d4900a5cb3))
- extend range over the merge reconciliation ([025697b](https://github.com/schiste/toolhub-evolved/commit/025697b15293884266786e522d63f1ed6fc03ac3))
- note derived lock reclamation ([8c31870](https://github.com/schiste/toolhub-evolved/commit/8c31870792061202875e5e735f4041577ea6c3db))
- note upstream-driven lookup pacing ([da02cc6](https://github.com/schiste/toolhub-evolved/commit/da02cc665397da78c893d8874f7ab3e7fdb52796))
- note cursor-bounded registry lookups ([ca20756](https://github.com/schiste/toolhub-evolved/commit/ca20756a42e8ef2d6a4cfd49e5b81aebeb0d8793))
- advertise the task and audience facets everywhere they work ([ba36fde](https://github.com/schiste/toolhub-evolved/commit/ba36fdef1a90738a4ac1ccad5c40de55b8ab9b91))

### Operations

- derive lock reclamation from each job's own timeout ([459eae4](https://github.com/schiste/toolhub-evolved/commit/459eae41e6c1906075e6195e5014a1479c23c388))

### Refactoring

- one request-normalization path for REST and MCP ([c38942b](https://github.com/schiste/toolhub-evolved/commit/c38942bdb991875062288b3a62782662d6b07d29))
- share filter cleaning and INTERSECT building ([47b17b2](https://github.com/schiste/toolhub-evolved/commit/47b17b2919520a4688c8a5a7f9852e216c10939a))

### Tests

- wait for enrichment before geometry ([7ad1c73](https://github.com/schiste/toolhub-evolved/commit/7ad1c73bd703173edf301057e184855e9eff03da))
- align cards and await author panel ([b912ba5](https://github.com/schiste/toolhub-evolved/commit/b912ba533b90cda7a5984e6b1e20b778f7fde0c7))
- cover production delivery boundaries ([bb1b92d](https://github.com/schiste/toolhub-evolved/commit/bb1b92d3428e167147f965c031743ed6c584ae7e))
- reset the JS thresholds to a working ratchet ([f327bbd](https://github.com/schiste/toolhub-evolved/commit/f327bbdd8f1b6140a904e8ec800e453cec3d3e71))
- close the coverage gaps on the new discovery code ([4f04cd5](https://github.com/schiste/toolhub-evolved/commit/4f04cd5d4bb51c41f8c387ae5c1f43572d844094))

### Maintenance

- align review branch with integration ([3ba4005](https://github.com/schiste/toolhub-evolved/commit/3ba40058a5044f94d0a6fb9f284b0750d38a386b))

### Other

- promote session 20 (Generalize proven person links across all tool cards) ([dce248b](https://github.com/schiste/toolhub-evolved/commit/dce248b287fca1b9d5d428b1ff2d1e9ee2681914))
- promote session 19 (Fix owner identity matching and by-person tool listings) ([1cb1f01](https://github.com/schiste/toolhub-evolved/commit/1cb1f0165c92bc5ab05507e34b7b6239236e1300))
- promote session 18 (Decouple OAuth login from long-running identity reconciliation locks and handle transient database contention) ([6eab247](https://github.com/schiste/toolhub-evolved/commit/6eab247dd841f863f5791f3eda9c03d2a50a1805))
- promote session 17 (Fix large digest storage and add live LiftWing preflight) ([d1ed4de](https://github.com/schiste/toolhub-evolved/commit/d1ed4de70ff662aee022fb55f820134978f6402c))
- promote session 16 (Bound LiftWing digest requests and expose generation failures) ([51504be](https://github.com/schiste/toolhub-evolved/commit/51504be753a1fd3f0bd1bf658aaf6852e235b82c))
- promote session 15 (Harden digest operations and redesign digest reading experience) ([cd99b1a](https://github.com/schiste/toolhub-evolved/commit/cd99b1ab3e14eeaedb32685a609c3f61af8695c3))
- promote session 14 (Reduce technical release notes to deployment contract limit) ([e7ad3d3](https://github.com/schiste/toolhub-evolved/commit/e7ad3d3016cbc1310381e8c1a47af8cffdc501d2))
- Merge pull request #142 from schiste/agent/digest-attribution-release ([e5a9e2d](https://github.com/schiste/toolhub-evolved/commit/e5a9e2d8eba1184371122b809c316bf8f091f00f))
- reconcile pending queue entry 13 (session 12) ([f0fa162](https://github.com/schiste/toolhub-evolved/commit/f0fa162d25397b0626d1db87f00dbbda2ea00289))
- Merge pull request #141 from schiste/fix/historical-digest-examples ([7033b70](https://github.com/schiste/toolhub-evolved/commit/7033b70ec0241a9f01ab7ac5577dd74039b53e38))
- Merge pull request #140 from schiste/fix/historical-digest-examples ([f4b571f](https://github.com/schiste/toolhub-evolved/commit/f4b571fc9487f0bc5a50292bc1df63c671681074))
- Merge pull request #139 from schiste/fix/historical-digest-examples ([e245005](https://github.com/schiste/toolhub-evolved/commit/e24500507e5e0e1faa02d05f2261a98a08661e3e))
- Merge pull request #138 from schiste/agent/reconcile-validate-and-release-toolhub-d ([2195881](https://github.com/schiste/toolhub-evolved/commit/2195881245f0c557ea600b3f4098f899c81d94b2))
- Merge pull request #134 from schiste/feat/toolhub-discovery-facets ([f5e5254](https://github.com/schiste/toolhub-evolved/commit/f5e52544c123c7e96b8bb932c912725a1695a08b))
- Merge remote-tracking branch 'origin/main' into feat/toolhub-discovery-facets ([ebea8da](https://github.com/schiste/toolhub-evolved/commit/ebea8da20d8ed9c208cd8ee67a21302b78ef3b9c))

## 2026-08-13

### Features

- add thin toolhub-discovery skill, fix prose CI on plan docs ([0078262](https://github.com/schiste/toolhub-evolved/commit/0078262321e6b6fd7ee12d12d65ab97c017cebc2))
- advertise purpose filters to MCP clients, pin fail-loud search ([4db6169](https://github.com/schiste/toolhub-evolved/commit/4db616986769a5887cc6a12b8054b68ec5740c50))
- implement MCP server for catalog discovery (Phase 4 Tasks 1-4) ([e80e590](https://github.com/schiste/toolhub-evolved/commit/e80e590cfb88f042068701ffad1e6c33ca71fa14))
- expose tasks and audiences as discovery filters ([f9aff6e](https://github.com/schiste/toolhub-evolved/commit/f9aff6e4c5b665c6bcaa713a2c0eb176c54275c1))
- mint people from verified CentralAuth global ids ([41d4ff6](https://github.com/schiste/toolhub-evolved/commit/41d4ff6124b5826f9c845bbd65664461b2d454f1))
- rate-limit and cache facet discovery reads ([8a2c9a0](https://github.com/schiste/toolhub-evolved/commit/8a2c9a0154426410ad4dd28938542dc35df5db11))
- add facet discovery endpoints ([947987d](https://github.com/schiste/toolhub-evolved/commit/947987d99a53c77e11b0a8276daf41c23b3c098f))
- shared tool summary and coverage for facet discovery ([8a2d40e](https://github.com/schiste/toolhub-evolved/commit/8a2d40ea07d7b9303bd8dcde2d777dc18029881f))
- ranked canonical tool search with FTS and keyword indexing ([506568f](https://github.com/schiste/toolhub-evolved/commit/506568f50fa9bd35485a94112a8c7abc38a3466d))
- resolve handle-shaped labels as registry candidates ([47607b7](https://github.com/schiste/toolhub-evolved/commit/47607b759b7ff456d15aaa4601de4cfacb89a8eb))
- add the label shape gate and measure what it admits ([438220c](https://github.com/schiste/toolhub-evolved/commit/438220c6cd045580fb6489d10cc980376c69d8b0))
- retarget facet queries to unified CatalogFacetValue table ([8f198fe](https://github.com/schiste/toolhub-evolved/commit/8f198fe9a69a36eaf4eae79d7caf7a0b1352c37e))
- emit analyzer-derived facets into catalog projection ([871dde9](https://github.com/schiste/toolhub-evolved/commit/871dde93f165c49bcf2d14b3c4639581ccdd2552))
- add declared-facet filters to tool discovery helpers ([6cde93a](https://github.com/schiste/toolhub-evolved/commit/6cde93a15747cc07395c01a266ad2835f8925a9b))
- add facet query helpers for tool discovery ([15ed8b7](https://github.com/schiste/toolhub-evolved/commit/15ed8b78ea5178e669ff8882b4fd2c49a9daf73f))
- extract analyzer findings into tool signal facets ([e7b080b](https://github.com/schiste/toolhub-evolved/commit/e7b080b1ce3ba6f9569638085002e926a151cc97))
- add ToolSignalFacet model for queryable tool signals ([3c5a083](https://github.com/schiste/toolhub-evolved/commit/3c5a083d52659e722e776733b5b491dcc4875071))
- publish background job health at /workers ([a568851](https://github.com/schiste/toolhub-evolved/commit/a5688511de69c417f952458bc9929fbdc0350cdc))
- resolve labels an independent edge corroborates ([670c24d](https://github.com/schiste/toolhub-evolved/commit/670c24d9b2a4523c375dd8832b3af00c102705f2))
- measure the attribution resolution funnel ([b5edca3](https://github.com/schiste/toolhub-evolved/commit/b5edca34f3105b2ef667c25feb7ee8bfdcd33b92))
- bind wiki user links as structured handles ([faba4c5](https://github.com/schiste/toolhub-evolved/commit/faba4c517d781662df117eb14e73dda136245669))
- surface catalog quality statistics ([989574a](https://github.com/schiste/toolhub-evolved/commit/989574a9a462eefd7bc67f7f9111b74b8fefea4a))
- add catalog quality statistics API ([8afd33d](https://github.com/schiste/toolhub-evolved/commit/8afd33d93da598d88ec65e34bf700672a013b505))
- reconcile identities across toolinfo sources ([221b507](https://github.com/schiste/toolhub-evolved/commit/221b507853db6f243417a58fb92a2b89d5f94e27))
- normalize multi-author tool metadata ([b8def7d](https://github.com/schiste/toolhub-evolved/commit/b8def7d9e076005ba835c1e6ac16dc37f71da1d1))
- disclose all tool authors ([2022cbc](https://github.com/schiste/toolhub-evolved/commit/2022cbcf5d0745b569f1159e6602335e6dabc081))

### Fixes

- stop trusting the engine's pluralCategories order ([f1a1260](https://github.com/schiste/toolhub-evolved/commit/f1a1260345fb1e0a6f138c46504d27967c32d25e))
- assert true total, and correct search-query guidance ([ac005dc](https://github.com/schiste/toolhub-evolved/commit/ac005dc4e5d1bdb9300939bcb9c16acadd195430))
- address code review feedback for Phase 1 ([c9c0579](https://github.com/schiste/toolhub-evolved/commit/c9c057907473396247a795a94da6325d21cfbd8a))
- optimize refresh_candidates query performance ([e9b7cd2](https://github.com/schiste/toolhub-evolved/commit/e9b7cd28211f0c2e77ddec4a9298a168794d15fd))
- address code review feedback for toolhub-discovery phase 1 ([342a9ee](https://github.com/schiste/toolhub-evolved/commit/342a9ee78a6d6439ea5b42a3ea7b1a82946b89e0))
- address mutation testing issues in tool facets module ([807d195](https://github.com/schiste/toolhub-evolved/commit/807d1952a217d10d56adf536377340907bbb752b))
- tolerate a pending scan row with no checked_at ([bb29294](https://github.com/schiste/toolhub-evolved/commit/bb29294616c7bea97a25dcdcede5ab85803a04bb))
- state what a job's exit code means to the guard ([841ba52](https://github.com/schiste/toolhub-evolved/commit/841ba52243545e6b2c6543c732c8eb4d75d4d937))
- retry a tripped breaker after a cooldown ([8a670df](https://github.com/schiste/toolhub-evolved/commit/8a670df7e67ce132cd90c2f7b651b8b069f14d40))
- reclaim guard locks a killed run abandoned ([4e59f7f](https://github.com/schiste/toolhub-evolved/commit/4e59f7f65e6dab79f394cae1d4d059687d83e01a))
- keep source reconciliation runs schema-safe ([462d44c](https://github.com/schiste/toolhub-evolved/commit/462d44c9be68b25410f9b79f22cc6c3a1e56b826))
- map Toolforge projects to canonical tools ([5a9d023](https://github.com/schiste/toolhub-evolved/commit/5a9d0233816716d258d5b0b272ea752454e2ea2b))
- bypass cache for catalog snapshots ([e2ea76b](https://github.com/schiste/toolhub-evolved/commit/e2ea76b5a6312405859ab805a23836abb3ab9b1e))

### Performance

- scope durable mapping reapply to the tool's own people ([b232d28](https://github.com/schiste/toolhub-evolved/commit/b232d280591b93dbfe1497213ba032866b657e6a))
- shrink the incremental drain's lock window ([31686a4](https://github.com/schiste/toolhub-evolved/commit/31686a4401dc2c68519c85a76d179dc8f1568d3b))
- avoid unchanged identity audit writes ([7cc41a0](https://github.com/schiste/toolhub-evolved/commit/7cc41a0badd7d0e5ce29eafce50587c0d4afb36b))
- isolate candidate identity discovery ([231831f](https://github.com/schiste/toolhub-evolved/commit/231831fba66f375fc2cfe2efdacf4980cd93d570))
- skip complete identity migration rows ([4b8047d](https://github.com/schiste/toolhub-evolved/commit/4b8047dcbbedc7920fb870697b675b0cc3ac2818))
- fingerprint semantic identity inputs ([d7d9922](https://github.com/schiste/toolhub-evolved/commit/d7d99227ad548ad608d37d88276f69dd5b9c42a8))
- reconcile changed identity sources only ([ac0cc09](https://github.com/schiste/toolhub-evolved/commit/ac0cc0983aa0aea8b05ff5a6b155394c4ae00116))
- batch stable identity synchronization ([541a49e](https://github.com/schiste/toolhub-evolved/commit/541a49e25ecc3b596d3335ad09acbd31f9d69f76))

### Interface and accessibility

- use imperative mood in facet counter docstrings ([20f58a1](https://github.com/schiste/toolhub-evolved/commit/20f58a17a5dda8000216a6bf9a067ca46f3d42bc))

### Documentation

- document MCP server endpoint (Phase 4 Task 5) ([8f4d548](https://github.com/schiste/toolhub-evolved/commit/8f4d548e55ef362b786faedc6280947828c860d2))
- note people minted from registry ids ([5139341](https://github.com/schiste/toolhub-evolved/commit/5139341e1d342d68f825956f767a66568c18b2f3))
- fail loudly when Toolhub search is unavailable ([0badecc](https://github.com/schiste/toolhub-evolved/commit/0badecc106714aa177cbea66cf882b613a9861c0))
- keep probe queries short for the same reason as tool queries ([68dac76](https://github.com/schiste/toolhub-evolved/commit/68dac7601d0951fd464f791fb54d02d72d7fc5a2))
- delegate search_tools to upstream Toolhub search ([9b29302](https://github.com/schiste/toolhub-evolved/commit/9b29302df593811e0d6186f8c0d86cf2c4b66860))
- record Phase 2 supersession and rationale ([578c363](https://github.com/schiste/toolhub-evolved/commit/578c363d2ae7c96b5341263f0e51681f5cd5cbd2))
- describe registry candidate resolution ([30e31a0](https://github.com/schiste/toolhub-evolved/commit/30e31a0a86f9d00d9d679f261c85d070aa6400f8))
- align design plan with the implemented facet design ([8d1dc42](https://github.com/schiste/toolhub-evolved/commit/8d1dc4284a54fa6eca83d30f677b13d475429109))
- note the label shape classification ([39c01e1](https://github.com/schiste/toolhub-evolved/commit/39c01e1cc074872f926e71a7a1f54652b254b58b))
- extend range over the shared setup change ([c4016ed](https://github.com/schiste/toolhub-evolved/commit/c4016ed1c10f5ede6f1466c4c72c057e7209fc01))
- revert to one facet table, emitted by the projection ([ec50a74](https://github.com/schiste/toolhub-evolved/commit/ec50a748370b6f35f12cc2e473ec2b507291e8a8))
- record why facet signals warrant a separate table ([0f2e6a5](https://github.com/schiste/toolhub-evolved/commit/0f2e6a54dbce79ac20fd43d9fd791d4dc887856a))
- scope ToolSignalFacet to analyzer-derived signals only ([ee64741](https://github.com/schiste/toolhub-evolved/commit/ee64741e617a36bfd6da2672b0011244f5304a74))
- note the mapping reapply optimization ([54d0cfd](https://github.com/schiste/toolhub-evolved/commit/54d0cfd6b66a550d434ba54349d3bb0d12b64c38))
- record operator confirmation in phase 5 checklist ([53f90b6](https://github.com/schiste/toolhub-evolved/commit/53f90b6ccbc7710dca90f5f9224aece82e86afbd))
- add toolhub-discovery implementation plan (5 phases) ([a3162cd](https://github.com/schiste/toolhub-evolved/commit/a3162cd6317e58deef46b3fb7dc68cdfba7a817e))
- note the drain lock-window change ([ebc158b](https://github.com/schiste/toolhub-evolved/commit/ebc158bb080dda0d03aad538a51a527bf5ec0493))
- note the repository analysis crash fix ([2eca844](https://github.com/schiste/toolhub-evolved/commit/2eca84412145b216844bdff031933f84ae82e73f))
- describe the job scaffold and duplication gate ([0fc0586](https://github.com/schiste/toolhub-evolved/commit/0fc05864a0184312c2fed58433387fb27d572e7c))
- document local hooks and the aethyme broker ([adeb0a9](https://github.com/schiste/toolhub-evolved/commit/adeb0a96bc8e813ce741c2195f75127d2b217a8f))
- add toolhub-discovery prior-art search design plan ([b769de7](https://github.com/schiste/toolhub-evolved/commit/b769de72213bf385451ecf95be07a139b1f41059))
- describe the background workers page ([daa8e38](https://github.com/schiste/toolhub-evolved/commit/daa8e384cf240f3142e3b3d57ed854b1495c2866))
- describe scheduled-job lock recovery ([932209a](https://github.com/schiste/toolhub-evolved/commit/932209a8a4633ea5cca8651d4b73a0dbc29825f7))
- extend community release source range ([c6a1f4b](https://github.com/schiste/toolhub-evolved/commit/c6a1f4b8d9c640250fdb72572b7b20d88788007d))
- extend community release source range ([39b4c98](https://github.com/schiste/toolhub-evolved/commit/39b4c98e1c7234396a3ac6481a192215193e0f0f))
- extend community release source range ([784f3d3](https://github.com/schiste/toolhub-evolved/commit/784f3d36447909cc1fc14094d464947ee1415b9c))
- extend community release source range ([d966e5b](https://github.com/schiste/toolhub-evolved/commit/d966e5b3e0d7dfa0c3cf7ed5a74c652afecf65ef))
- extend community release source range ([4c73f68](https://github.com/schiste/toolhub-evolved/commit/4c73f68c3ae351e6c8dabe5232f40e844fb433a0))
- describe identity resolution improvements ([7112be0](https://github.com/schiste/toolhub-evolved/commit/7112be0fc484f0d99eafa25bba9517078f149c3c))
- extend community release source range ([fdccb37](https://github.com/schiste/toolhub-evolved/commit/fdccb3704b415eb5efc04f31cd3c37031875922b))
- clarify statistics cache warming ([6ea6b6e](https://github.com/schiste/toolhub-evolved/commit/6ea6b6ef5c50a3e26764826d0bdec23ee0bbbfcc))
- document last-good projection operations ([70545ab](https://github.com/schiste/toolhub-evolved/commit/70545ab20c7f348cb55d1e5816c685ef50d929d9))
- extend community release source range ([176a39d](https://github.com/schiste/toolhub-evolved/commit/176a39d2407ae26cc3f30ac0e1af5aa555253dad))
- include catalog quality statistics ([fbd39fe](https://github.com/schiste/toolhub-evolved/commit/fbd39fe5d4ddda198eadde2e69f75bade9c1111c))
- extend community release source range ([b73622f](https://github.com/schiste/toolhub-evolved/commit/b73622fc8a0d95c59780ebdcdade2bbb920a6660))
- include canonical Toolforge aliases ([862157b](https://github.com/schiste/toolhub-evolved/commit/862157bcc02b66be13a4b742af9491e933670a9a))
- document Toolforge project aliases ([17037e4](https://github.com/schiste/toolhub-evolved/commit/17037e4dbf485573bdf93b3d2ae251c2366f96ce))
- include fresh catalog snapshots ([868f78a](https://github.com/schiste/toolhub-evolved/commit/868f78a722bdd2d9d51ac3de02cbe4d3117cfcdd))
- fold card updates into community release ([4dfa744](https://github.com/schiste/toolhub-evolved/commit/4dfa7441961e8dfb4876a7046d133b22fde4a313))

### Operations

- enable registry candidate discovery hourly ([5cd83c4](https://github.com/schiste/toolhub-evolved/commit/5cd83c4c64983c568e39edcae30376301cbfc2f9))
- shorten and instrument production deploys ([905724f](https://github.com/schiste/toolhub-evolved/commit/905724f2e582dba0ad501e8abb38504c9d6a3aca))
- coordinate last-good projection refreshes ([040a90d](https://github.com/schiste/toolhub-evolved/commit/040a90d88de1378df41e694e00ced19aa74ed191))
- schedule source identity reconciliation ([91cd14e](https://github.com/schiste/toolhub-evolved/commit/91cd14e607418177b8efa032773e82f9dc3b1f56))

### Refactoring

- use the shared setup in account sync too ([7ff2c72](https://github.com/schiste/toolhub-evolved/commit/7ff2c72785e7a98210e2f364e2c2c4bcd3c68eab))
- share the JSON report load cycle ([5b1e2b0](https://github.com/schiste/toolhub-evolved/commit/5b1e2b06ced45d1b4ae11336d18247a74ebb728e))
- share one entrypoint scaffold across the jobs ([f656a0c](https://github.com/schiste/toolhub-evolved/commit/f656a0c2d97076f5a1956f08624977c2828ab37a))
- simplify maintainer trust cues ([bf45bdb](https://github.com/schiste/toolhub-evolved/commit/bf45bdb996b9d4c03307935520ab812c20b14ea5))

### Tests

- hold the whole measured tree at 100% and ratchet to it ([49cb3f6](https://github.com/schiste/toolhub-evolved/commit/49cb3f600746fd956846ac50baed146561b2619a))
- cover the eight largest backend coverage gaps ([6d67a59](https://github.com/schiste/toolhub-evolved/commit/6d67a59498b0850e7e0837345665bff2ac78e0c4))
- pin scan -> projection facet delivery end to end ([37c6556](https://github.com/schiste/toolhub-evolved/commit/37c65562a8e8f6ff2012381a73c7d2beb0379042))
- make the containment test exercise the real savepoint ([fd30279](https://github.com/schiste/toolhub-evolved/commit/fd30279856c904816d3b5fa970bfc93827ac36d8))
- add multi-empty-filter edge case tests ([a03b03f](https://github.com/schiste/toolhub-evolved/commit/a03b03facdadc19089b8e70f076b44917afefbc5))
- add edge case coverage for tool_facets ([a283df5](https://github.com/schiste/toolhub-evolved/commit/a283df54c4d750555268e633f146a508455ef6c9))
- cover incremental projection maintenance ([ea0f035](https://github.com/schiste/toolhub-evolved/commit/ea0f03529f37d1a470137c45024d94889d140746))

### Maintenance

- move to ruff 0.16.3 and satisfy its newly stable rules ([af74a46](https://github.com/schiste/toolhub-evolved/commit/af74a46504f1efc619a74057bf030820d87e3abd))
- green the spell check on a docstring ([a07a912](https://github.com/schiste/toolhub-evolved/commit/a07a912a1f0e3c3e894fd28f5e2a130ebc03a1be))
- green the spell check on pushed code ([9783e03](https://github.com/schiste/toolhub-evolved/commit/9783e0364a93b080bd320391bc936c954790c73e))
- run the duplication gate over Python too ([6a4efc2](https://github.com/schiste/toolhub-evolved/commit/6a4efc2d091e55630fd78719f3c45c1350a73afa))
- recognize identity pipeline terminology ([5b17d13](https://github.com/schiste/toolhub-evolved/commit/5b17d13427f6871f9c4d743c69340fe3644aa6b6))

### Other

- Merge origin/main into feat/toolhub-discovery-facets ([bb89dea](https://github.com/schiste/toolhub-evolved/commit/bb89deaa5961108006de2d9c9e48f1b579c21b3d))
- Revert "feat: ranked canonical tool search with FTS and keyword indexing" ([baf6877](https://github.com/schiste/toolhub-evolved/commit/baf6877286ceb935be6a472ae80c5294a69b44fd))
- gate commits with pinned aethyme ruff checks ([af9936e](https://github.com/schiste/toolhub-evolved/commit/af9936e1ab38de4b28e9b893c71c44490e310df2))

## 2026-08-12

### Features

- reconnect Toolforge identities securely ([9e11e5d](https://github.com/schiste/toolhub-evolved/commit/9e11e5df7ab07ac27bc309169bac2469365bbe6e))
- verify reconnectable Toolforge accounts ([283b8ed](https://github.com/schiste/toolhub-evolved/commit/283b8edaf32020c3484ce685056a24b83564b338))
- add secure account reconnection proofs ([e42f7ce](https://github.com/schiste/toolhub-evolved/commit/e42f7cec731ae36380f64e51cbf4bcec9b8e5e58))
- bind immutable external accounts ([ace9c41](https://github.com/schiste/toolhub-evolved/commit/ace9c41c3d4d0a9196924d3d79f8e27eb818a8e3))
- project Toolforge accounts and memberships ([6d47959](https://github.com/schiste/toolhub-evolved/commit/6d479596a04ca539996a350de3eb1053cc84a3ba))
- publish curated deployment history ([c5ca659](https://github.com/schiste/toolhub-evolved/commit/c5ca65985c62c6066f081936ea95abd9141a6667))

### Fixes

- hide canonicalized identity aliases ([9087a7e](https://github.com/schiste/toolhub-evolved/commit/9087a7e8307a447df76c71b36a4b811c4c2acb18))
- show canonical tool relationships ([6003e09](https://github.com/schiste/toolhub-evolved/commit/6003e093694f2bdfd15936cea138aeb60160276e))
- reuse recent catalog snapshots ([e51ca77](https://github.com/schiste/toolhub-evolved/commit/e51ca773c5fbb307df5dbe25c64fcb746ce2882f))
- drain only catalog retirements ([90b98ad](https://github.com/schiste/toolhub-evolved/commit/90b98adfff4e3dc8d28daaca8f2406eadb9737c3))
- hide retired Toolhub index records ([bb80980](https://github.com/schiste/toolhub-evolved/commit/bb80980067a77de092c7b48f946f66407509be68))
- retire tools after complete snapshots ([5dbbb47](https://github.com/schiste/toolhub-evolved/commit/5dbbb47da0451483422a66a9acdca0f1fedeb54b))
- correct failure reporting and add log rotation ([d4a05a2](https://github.com/schiste/toolhub-evolved/commit/d4a05a2e64cb923985484f8e4a48260772127c98))
- recover from transient module failures ([19b5ec2](https://github.com/schiste/toolhub-evolved/commit/19b5ec25ed857e6b589825695d2a2718a46ebec7))
- expose only author and maintainer roles ([0067f89](https://github.com/schiste/toolhub-evolved/commit/0067f894153591f23d47d6d0071390330727cc47))
- keep authority edges internal ([dd67fda](https://github.com/schiste/toolhub-evolved/commit/dd67fda83dd81104cba111ffe61bffa835ad9d37))
- self-heal reapplied identity evidence ([ab38374](https://github.com/schiste/toolhub-evolved/commit/ab3837423204cee6f352ca817bb44c32132771da))
- present curated product releases ([ac82162](https://github.com/schiste/toolhub-evolved/commit/ac8216246bf5be42900dc18336eebd42074ee8f6))
- label the signing command ([5204f02](https://github.com/schiste/toolhub-evolved/commit/5204f027483a832420118cffd9fa7b525f0e4524))
- type connected identity payloads ([c2ff4ed](https://github.com/schiste/toolhub-evolved/commit/c2ff4ed56d1efc5e2e3cbda7687352fef8927255))
- publish structured author handles ([0e5c71f](https://github.com/schiste/toolhub-evolved/commit/0e5c71f28c390f4206d2813fda04368905c64463))
- reconcile multiple verified accounts ([1bffe0c](https://github.com/schiste/toolhub-evolved/commit/1bffe0cccb9be36edec22a201ad84973aa6811cb))
- reexec after updating script ([4416879](https://github.com/schiste/toolhub-evolved/commit/4416879c3e9680fd79e1843b395625ae997deed0))
- run account sync as bounded job ([eaf3f4d](https://github.com/schiste/toolhub-evolved/commit/eaf3f4d650131d6b656f04b83d2dd007ef474222))
- make route loading converge ([622d48c](https://github.com/schiste/toolhub-evolved/commit/622d48c8b25d6e36dfc4090387bfe111efed902c))

### Documentation

- extend community release range ([04730ed](https://github.com/schiste/toolhub-evolved/commit/04730edeaa4e2ff7a746181160fb8156f61085c4))
- extend community release range ([8d6266a](https://github.com/schiste/toolhub-evolved/commit/8d6266af19d40a2d38e47c7a6f64098fa91273ed))
- extend community release range ([3fdcf1a](https://github.com/schiste/toolhub-evolved/commit/3fdcf1ab8d5b5d7d39359d10805e6e082681906a))
- extend community release range ([c1ee530](https://github.com/schiste/toolhub-evolved/commit/c1ee530f2c2f554e1c08186fb2c80c14ab395139))
- extend community data lifecycle ([5c427a9](https://github.com/schiste/toolhub-evolved/commit/5c427a94ddf4d479e9c8ea9f6d1e0feded5b6786))
- describe job reliability and log rotation ([2fbe4cf](https://github.com/schiste/toolhub-evolved/commit/2fbe4cf0f14bb7dc8ca50df052485c84d151a158))
- extend community release range ([a33a1ab](https://github.com/schiste/toolhub-evolved/commit/a33a1abd59c9e18c167a4814082e2b8cb47eb494))
- clarify public relationship roles ([cc8b5d3](https://github.com/schiste/toolhub-evolved/commit/cc8b5d37c323c7b5093bd6311a45384b7e289651))
- include reconciliation self-healing ([f03ddd0](https://github.com/schiste/toolhub-evolved/commit/f03ddd017b69272332a04106266d3a5c057fc511))
- include fallback release seed ([9e56315](https://github.com/schiste/toolhub-evolved/commit/9e56315f11bf1576921e9e3cd629983287f48bd3))
- seal curated identity release ([24d3151](https://github.com/schiste/toolhub-evolved/commit/24d3151eb741b9c3ed7bee326ab71656df14caad))
- bundle identity reconciliation release ([8b7f996](https://github.com/schiste/toolhub-evolved/commit/8b7f9964148e6d03dab8629812d3a8e6a6693f0f))
- define reconciliation and reconnect contracts ([17e508e](https://github.com/schiste/toolhub-evolved/commit/17e508ed016d5337ea967247bb191ff6cea26264))
- seal production deployment range ([828d83a](https://github.com/schiste/toolhub-evolved/commit/828d83a6712c5a970220ca41393a401d79fb4c9b))
- finalize deployment release range ([1602d31](https://github.com/schiste/toolhub-evolved/commit/1602d31ec7d9202109b8d470b39772075e90dab4))
- extend reviewed release range ([748ca52](https://github.com/schiste/toolhub-evolved/commit/748ca52ba384b0037608dac64c1324c9649200b0))
- seal reviewed release range ([a76a8f2](https://github.com/schiste/toolhub-evolved/commit/a76a8f23843fdbd3a4e468b35b88f13e3cc2b450))

### Refactoring

- group deploys under curated releases ([039fd97](https://github.com/schiste/toolhub-evolved/commit/039fd979afe38530f6561a0d848c14f9e0e66cd1))
- remove legacy resolver cache ([6564020](https://github.com/schiste/toolhub-evolved/commit/6564020c4863b59626410b53c74d929e376706e5))
- separate unresolved attributions ([be66b2d](https://github.com/schiste/toolhub-evolved/commit/be66b2db7c23527094aaa348cede2f7cbaf0479f))
- share canonical account relationships ([7030622](https://github.com/schiste/toolhub-evolved/commit/70306226f553c238068d0135da73f8fc4f67d65c))
- use jobs for environment steps ([37634a0](https://github.com/schiste/toolhub-evolved/commit/37634a01c181a3665cfe1ffd059f260da257063f))

### Tests

- wait for settled interactive chrome ([b02b1c8](https://github.com/schiste/toolhub-evolved/commit/b02b1c82a66020cc05e5a6487cebe3ed4bab93cd))
- align integration guard contracts ([566562b](https://github.com/schiste/toolhub-evolved/commit/566562b505257a3cfe5ec90b76f7c9fec14d7b9d))

### Maintenance

- add empty fallback release manifest ([d983144](https://github.com/schiste/toolhub-evolved/commit/d983144e55c83b0a17c8ce94dc4206bac89ca3b0))
- add parallel preflight ([91a2807](https://github.com/schiste/toolhub-evolved/commit/91a28078910abdda6e93abba9ac81eafda6602d1))

## 2026-08-11

### Fixes

- preserve overlays during data refresh ([498dd52](https://github.com/schiste/toolhub-evolved/commit/498dd5266478d9a1353093d845dfceb53ad50904))
- coordinate pending state with navigation ([3c87220](https://github.com/schiste/toolhub-evolved/commit/3c87220b7b21f819f1c54b799931ebb709027e3e))
- stop same-route render loops ([a222236](https://github.com/schiste/toolhub-evolved/commit/a222236f606a3590451c74df7897205080cfad20))
- require trusted handle provenance ([369553c](https://github.com/schiste/toolhub-evolved/commit/369553c4d0bcd559ac30d52312347e8a4f2dbd92))

### Performance

- skip retired evidence backfill ([116ee3e](https://github.com/schiste/toolhub-evolved/commit/116ee3e0730230e57e572bb038a9d0fb8a6bda5c))

### Documentation

- record directory hardening ([9eadfdb](https://github.com/schiste/toolhub-evolved/commit/9eadfdba12cb6835ddf9b9bc3f60d3163a66e96a))
- note same-route loop fix ([f65d46b](https://github.com/schiste/toolhub-evolved/commit/f65d46b1c7e7c404ef24d07dc069dc4a69c3a8dc))
- record trusted identity projection ([eecf8a3](https://github.com/schiste/toolhub-evolved/commit/eecf8a3b50a7111ea8b992f8cabd7fc3cc421152))

### Tests

- allow installed Chromium ([04bfcf1](https://github.com/schiste/toolhub-evolved/commit/04bfcf1658bdb2bf6959df8c682769f6c4dd5659))
- contain background refresh work ([dcd5603](https://github.com/schiste/toolhub-evolved/commit/dcd5603c738e0e76ec4ddb9b24795699531a03e8))

## 2026-08-10

### Features

- present evidence-aware results ([d50d872](https://github.com/schiste/toolhub-evolved/commit/d50d8723994c28cd775333a5a3d913c9ab4b41a8))
- structure directory search results ([b2bea41](https://github.com/schiste/toolhub-evolved/commit/b2bea41b192fde6eb57242aa8b77a06186534c96))
- add relationship metrics to cards ([ecd870a](https://github.com/schiste/toolhub-evolved/commit/ecd870aef1352f32873ed35df1a58ba44271d3d9))
- show owner and maintainer tool counts ([a0712c8](https://github.com/schiste/toolhub-evolved/commit/a0712c8e8d4cc87c7838beb3128cb12074c03f38))
- expose per-role tool counts ([c99dc46](https://github.com/schiste/toolhub-evolved/commit/c99dc465764902c2a62971f802420feca2f9111b))

### Fixes

- keep label clusters out of review queue ([56a6361](https://github.com/schiste/toolhub-evolved/commit/56a63618122fc88f0412e148c07d89e29f4c12af))
- preserve relationship provenance ([1b7ecb5](https://github.com/schiste/toolhub-evolved/commit/1b7ecb5700238f9181e0c3506f814c976851eae7))
- prioritize duplicate identity clusters ([8541e5d](https://github.com/schiste/toolhub-evolved/commit/8541e5dbc55480ca752fd70e77fb86dc1bb17351))
- clarify mixed directory cards ([0d0dfe2](https://github.com/schiste/toolhub-evolved/commit/0d0dfe20659c7b57e903819b4f35ec038b64894c))
- rank first-class search results ([1cad2d7](https://github.com/schiste/toolhub-evolved/commit/1cad2d7804fcf8dab401e98387f7937b55cd2981))
- reconcile Toolsadmin account names ([6249cb3](https://github.com/schiste/toolhub-evolved/commit/6249cb3f0f8e89ad7439ebd4dcb70e9dbecb7bcb))
- use Wikimedia LDAP global IDs ([f3d13b2](https://github.com/schiste/toolhub-evolved/commit/f3d13b2fea01f7380687ca9df3deed6e55f5979e))
- reconcile verified wiki handles ([e069940](https://github.com/schiste/toolhub-evolved/commit/e06994025ccb16890f0dcaa23bdf523ab69dd0c2))
- tolerate stale advisory lock release ([910049f](https://github.com/schiste/toolhub-evolved/commit/910049ff14361e70ba02bd8ff3aa8424b3a110ca))
- consolidate duplicate pending conflicts ([26309de](https://github.com/schiste/toolhub-evolved/commit/26309deae2310d1daaa1d6a0cb47d74067fed319))
- enrich linked account results ([14f7a3f](https://github.com/schiste/toolhub-evolved/commit/14f7a3fdc5f49894ce4991bc659975c6d40f8a46))

### Documentation

- record evidence-aware directory release ([b92df08](https://github.com/schiste/toolhub-evolved/commit/b92df08ba7a5fbf6eb607e0ca241b797f9e01b5e))
- advance reviewed release range ([0e365ea](https://github.com/schiste/toolhub-evolved/commit/0e365ea5bbfd430af544b8fdca75f880d652d9f9))
- note duplicate-first reconciliation ([05729fb](https://github.com/schiste/toolhub-evolved/commit/05729fb33123b33c59fff86de676da4853b5338a))
- advance reviewed release range ([35710b4](https://github.com/schiste/toolhub-evolved/commit/35710b487e81150dda1b5eee2eda22cd0b49777a))
- explain stable identity reconciliation ([9bde089](https://github.com/schiste/toolhub-evolved/commit/9bde08958775aa9918289a04ae88871c2459e5d7))
- advance reviewed release range ([cfacc2c](https://github.com/schiste/toolhub-evolved/commit/cfacc2c3805db357bc2ad73f113673bd5f21f36c))
- clarify public identity reconciliation ([6dfe38d](https://github.com/schiste/toolhub-evolved/commit/6dfe38de2422bf1303a98c19a4d8cf2f276041a4))
- note long reconciliation reliability ([bbb452b](https://github.com/schiste/toolhub-evolved/commit/bbb452bafa014d1cd21ccb625756131cfadb153c))
- note reconciliation conflict cleanup ([aaade63](https://github.com/schiste/toolhub-evolved/commit/aaade63c586bf6b0b4f2962e737a829e64ab2caf))
- review community directory release notes ([2119677](https://github.com/schiste/toolhub-evolved/commit/2119677d9c8313d7ce2ff2b5c17d2dc392fe4093))

### Tests

- cover attribution trust breakdown ([0de7f0c](https://github.com/schiste/toolhub-evolved/commit/0de7f0c46d53d37b6ba3ca74713cdff806a5af7a))

## 2026-08-09

### Features

- align directory with catalog search ([1325295](https://github.com/schiste/toolhub-evolved/commit/13252958df5ea0dd198a8e4ef2fafafb28fd6cec))
- reconcile SUL-backed public identities ([13f7b6f](https://github.com/schiste/toolhub-evolved/commit/13f7b6f2623f2d016796bd6874f7778bb4a9e46f))
- materialize stable Toolhub account identities ([aa088e6](https://github.com/schiste/toolhub-evolved/commit/aa088e6bc3b4acfc5f92266aa7f5ccb98f7c040a))

### Operations

- refresh public identity links after account sync ([7e0763f](https://github.com/schiste/toolhub-evolved/commit/7e0763fb086aa104729771d25ffb513305073d47))

## 2026-08-07

### Features

- replace community tabs with unified search ([f394bb6](https://github.com/schiste/toolhub-evolved/commit/f394bb6a865a553ca78260224756f343cc215e2e))
- unify community identity search ([7f09125](https://github.com/schiste/toolhub-evolved/commit/7f091252aa2d4de72a600443de2f4d9c5a28ca66))
- validate message files, 404 missing catalogs, fix the JS budget ([76e38c6](https://github.com/schiste/toolhub-evolved/commit/76e38c6c2cfaa32165aa3159967863c551c49017))
- move messages to the banana format translatewiki speaks ([b933500](https://github.com/schiste/toolhub-evolved/commit/b9335007e76a1cfe4a9da7ea2b5e82ab5f6a545b))
- unify people accounts and contributors ([b37918c](https://github.com/schiste/toolhub-evolved/commit/b37918c3464498e0c9119f0ab503ab68809d0d0d))
- add account and contributor APIs ([9ad048e](https://github.com/schiste/toolhub-evolved/commit/9ad048e236e23c3debf3753355f4cb166b84cb77))
- add resumable official projection ([d1c2077](https://github.com/schiste/toolhub-evolved/commit/d1c2077a1d59d0b29635d1b9f550e952b1070072))

### Fixes

- clear the gates that were failing CI ([b951bbb](https://github.com/schiste/toolhub-evolved/commit/b951bbbeb50199e3bb8c4e096b5e44bf4ae6c1ba))
- preserve community trust badge colors ([7a9cfc4](https://github.com/schiste/toolhub-evolved/commit/7a9cfc452d293f136ff3763487a2151c152791ab))
- require complete deploy refresh ([01602a9](https://github.com/schiste/toolhub-evolved/commit/01602a9a8350301833c17445db80d2c21f28eff2))

### Documentation

- regenerate FEATURES.md for the community directory ([1a09d5b](https://github.com/schiste/toolhub-evolved/commit/1a09d5b9e2acf7454463ff14c42a67bebfa22f22))
- define unified community evidence contract ([27e2a74](https://github.com/schiste/toolhub-evolved/commit/27e2a742c6025fa454f5741c43212b5c95a03ee7))
- define directory and API contracts ([2992328](https://github.com/schiste/toolhub-evolved/commit/299232886880aecd3ad549ec38a38090a8fd40b5))

### Operations

- refresh complete projection on deploy ([ef59a40](https://github.com/schiste/toolhub-evolved/commit/ef59a404c9074a355dec15f46b97e2bb740f8fdd))

### Tests

- hold the reverse proxy at 100% and ratchet the rest ([c8a78c3](https://github.com/schiste/toolhub-evolved/commit/c8a78c33cb95470b979a22a926a56b2ebb5bb2ce))
- cover account directory browser flows ([237245f](https://github.com/schiste/toolhub-evolved/commit/237245f492f472cf9b064e05d8c471652fc0203f))

### Maintenance

- preserve type-check baseline ([63e2b04](https://github.com/schiste/toolhub-evolved/commit/63e2b0420eef206033d24fe775f65822e719668c))

### Other

- leave people_index.py to the session that is editing it ([71cc31f](https://github.com/schiste/toolhub-evolved/commit/71cc31ff464bd7e7376656bb823e9582cd68e3e3))
- Merge main into the i18n banana migration ([8aea533](https://github.com/schiste/toolhub-evolved/commit/8aea53368277550b47e550652bd6e3ac473c00b8))

## 2026-08-06

### Features

- add paginated profile tool UI ([51891a7](https://github.com/schiste/toolhub-evolved/commit/51891a70f66af1902b5f8b50938267febf792e03))
- paginate profile tool summaries ([f181ad9](https://github.com/schiste/toolhub-evolved/commit/f181ad9b60f47f371719488cc1dd6c87eb3fdffd))
- build URL-driven directory UI ([f6bbab7](https://github.com/schiste/toolhub-evolved/commit/f6bbab75a267879e30996e3475c10494830a481f))
- add directory search client ([727b321](https://github.com/schiste/toolhub-evolved/commit/727b321155b3c199a625b8c7516a3c61b617de0b))
- add paginated directory search ([e4854c7](https://github.com/schiste/toolhub-evolved/commit/e4854c767bc5ba40466e3bc46c452b9f733282ea))
- expose tool viewer relationship context ([1f78e92](https://github.com/schiste/toolhub-evolved/commit/1f78e92d087fa05f43f3da947fdd7e5b51e0a375))
- reveal relationship trust on profiles ([a36b765](https://github.com/schiste/toolhub-evolved/commit/a36b76510eb6135883f629139814de558ef2ed81))
- centralize relationship trust labels ([f6ddf8d](https://github.com/schiste/toolhub-evolved/commit/f6ddf8d067d5e718dba19c14265865503dc6952f))
- expose relationship verification evidence ([92da44d](https://github.com/schiste/toolhub-evolved/commit/92da44d9f37030858425d9fdceaf0876897a2889))
- disambiguate legacy author routes ([6dac4b1](https://github.com/schiste/toolhub-evolved/commit/6dac4b1e22dc2b9d66ab61ab5add34f044ecc12c))
- persist Toolforge account evidence ([bb05941](https://github.com/schiste/toolhub-evolved/commit/bb059419aade04c256f52b20062a461cfc63d4db))
- apply durable identity review decisions ([62f2055](https://github.com/schiste/toolhub-evolved/commit/62f2055f0d8e1a44ec62008eeecbf4da3ae65aca))
- queue evidence-backed identity candidates ([7f25c52](https://github.com/schiste/toolhub-evolved/commit/7f25c52e3854d625700c156f1170133d928c8252))
- discover exact Toolhub identities ([9a74d90](https://github.com/schiste/toolhub-evolved/commit/9a74d9042e70e7f75bf18dfee69e6264e7385845))
- retain Wikimedia global identity ([13e4cca](https://github.com/schiste/toolhub-evolved/commit/13e4cca16dfbacb8dbc03b12b63956b8246ff179))
- label unresolved directory evidence ([0d86a4c](https://github.com/schiste/toolhub-evolved/commit/0d86a4cfea1a432a75adaee5a13444d222143180))
- fail the push when the release notes do not describe it ([081e06f](https://github.com/schiste/toolhub-evolved/commit/081e06f0ea6c362eaa2631833d397c4724e1ae45))

### Fixes

- clamp profile tool pages ([dc7c67b](https://github.com/schiste/toolhub-evolved/commit/dc7c67b0b7db4368418a24a68507bbd8ac5fdaaa))
- remove profile tool request fan-out ([df972d7](https://github.com/schiste/toolhub-evolved/commit/df972d769028a619fec49958970b235c18dff49f))
- harden directory navigation failures ([1a1eff5](https://github.com/schiste/toolhub-evolved/commit/1a1eff505e9e750db383981941df97bc60056d03))
- label actions by verified viewer role ([02c8e11](https://github.com/schiste/toolhub-evolved/commit/02c8e1119db2148ec06496af2313a631fabc6a66))
- label maintainer verification explicitly ([82850e4](https://github.com/schiste/toolhub-evolved/commit/82850e473468ac170f7e96abd1904027607c5feb))
- preserve evidence callback typing ([94815a2](https://github.com/schiste/toolhub-evolved/commit/94815a2109708a39776332825ede16278c32872f))
- distinguish maintainer relationship trust ([9fd446f](https://github.com/schiste/toolhub-evolved/commit/9fd446f1fa93351b2e42c3a1b2e70d214e4f8bf9))
- resolve legacy routes by unique handles ([679d4db](https://github.com/schiste/toolhub-evolved/commit/679d4db8fb4014adf5415f25bdde312d90b909c2))
- quarantine stable identity conflicts ([f31f3af](https://github.com/schiste/toolhub-evolved/commit/f31f3af4ac3e370fee40c34e463380369a6627f2))
- separate unresolved attributions ([534dd18](https://github.com/schiste/toolhub-evolved/commit/534dd18841dce2e2d1aae956fd86208b98db1c6a))
- ignore a gzipped twin older than the file it stands for ([4fb37e2](https://github.com/schiste/toolhub-evolved/commit/4fb37e29f91dc4f39126f077843ae6eeb19c4e46))

### Interface and accessibility

- restore ruff formatting ([61a6a96](https://github.com/schiste/toolhub-evolved/commit/61a6a96aea3f9b17583cda245d6c5c484d28ac31))

### Documentation

- extend reviewed release range ([43f2386](https://github.com/schiste/toolhub-evolved/commit/43f23863f599be192d9059b301c9ced0f6d634c4))
- document legacy route disambiguation ([402d4c2](https://github.com/schiste/toolhub-evolved/commit/402d4c28686a416308a51110581a37bbd5545157))
- finalize reviewed release range ([a6a5dd3](https://github.com/schiste/toolhub-evolved/commit/a6a5dd37444b564202c64b755209dd3f95c22fa5))
- advance reviewed release notes ([16d9d40](https://github.com/schiste/toolhub-evolved/commit/16d9d4098588e87ff80390f4c9054ed7e7250ba4))
- document identity reconciliation operations ([4494063](https://github.com/schiste/toolhub-evolved/commit/44940638a916a59b0699e7ed4e7773d93615dea1))
- define public identity policy ([401149a](https://github.com/schiste/toolhub-evolved/commit/401149a67eb64072c049261af4dd2a266590a529))
- note the output/ ignore rule and move the range forward ([38de4ff](https://github.com/schiste/toolhub-evolved/commit/38de4ff92979b9896033cf1a3082b9a9fc98cc91))
- describe the release-notes gate in the release notes ([716b84e](https://github.com/schiste/toolhub-evolved/commit/716b84ea879ebec9d1d26bacf6975b3e0db8809c))
- rewrite the release notes, which had been stale for 34 commits ([a75efed](https://github.com/schiste/toolhub-evolved/commit/a75efed50d3449c617bb2c725de12b8f7f5fe187))

### Refactoring

- centralize identity evidence policy ([1936912](https://github.com/schiste/toolhub-evolved/commit/193691276ac20ad9392c77304e17daa5575d6818))

### Tests

- cover prolific profile pagination ([9e8b855](https://github.com/schiste/toolhub-evolved/commit/9e8b8554ee6a4c8a8df7223a85a348d19fc179e6))
- cover directory search contract ([ba9638e](https://github.com/schiste/toolhub-evolved/commit/ba9638e4290a1af52fe4e462aac6d44498c6115d))
- cover contributor action boundaries ([a104993](https://github.com/schiste/toolhub-evolved/commit/a1049938312c64ea7f51cada0a1f1cc533511636))
- inventory public handle resolver ([360d587](https://github.com/schiste/toolhub-evolved/commit/360d587d28032d1213833d839d224fa7ae278ac4))
- align Toolsadmin handle namespace ([4c77dbb](https://github.com/schiste/toolhub-evolved/commit/4c77dbb8104b0d30f8e9a0a087f19fdd50158426))
- enforce identity acceptance criteria ([6accefa](https://github.com/schiste/toolhub-evolved/commit/6accefaacbeb6e6d99683ae87bfaa786f45cf3e0))

### Maintenance

- ignore output/, which can contain signed-in session state ([24be52a](https://github.com/schiste/toolhub-evolved/commit/24be52a65ad5768ad1d82b278e26ce1542bd816d))

## 2026-08-05

### Fixes

- report a scan failure that cannot be recorded instead of dropping it ([6d5c835](https://github.com/schiste/toolhub-evolved/commit/6d5c8355a570a2cc038ac015ae75bd64a008d385))
- move the issue-publish failure messages into their exception classes ([c6f4254](https://github.com/schiste/toolhub-evolved/commit/c6f42548246e283d70618a04fdfb309290593664))
- clear the three lint findings in user_tool_cache ([5f0b71b](https://github.com/schiste/toolhub-evolved/commit/5f0b71b11f750759588362e2bbb935df89058f41))
- route every summary cache write through one guarded path ([5969bfa](https://github.com/schiste/toolhub-evolved/commit/5969bfab19fee65803f631a5b06bb5efde8408a4))
- stop the card view from evicting a stored full summary ([801ccf9](https://github.com/schiste/toolhub-evolved/commit/801ccf905df9312c4d73d23eae0bd6629f537b52))
- keep the requested view through the deferred summary queue ([cff7225](https://github.com/schiste/toolhub-evolved/commit/cff722510ab7cdbe995f12d5488b43beb779c3c4))

### Performance

- serve built static assets from memory instead of NFS ([29e7ff0](https://github.com/schiste/toolhub-evolved/commit/29e7ff04357fdeef1cbf878a76215712912e6952))
- gzip static assets at build time instead of per request ([435e9d7](https://github.com/schiste/toolhub-evolved/commit/435e9d715bc0503604e2d14f3bcada8a1253b58e))

### Interface and accessibility

- apply ruff format to five files it had drifted from ([6d6db56](https://github.com/schiste/toolhub-evolved/commit/6d6db567612c721c078d61f070e953b11b863e51))

### Refactoring

- move three helpers to modules that match what they do ([480d36e](https://github.com/schiste/toolhub-evolved/commit/480d36ec9068ad3fe4a89b921fb89fb959b9fb7a))
- give the shared v1 helpers a home and public names ([29876c3](https://github.com/schiste/toolhub-evolved/commit/29876c382d6f030e17f26490e20dad28ae293728))
- split the last six multi-route families out of v1.py ([af8a51c](https://github.com/schiste/toolhub-evolved/commit/af8a51cbb69445db3e268bce67fed65d9362e9f8))
- stop exporting three internal-only symbols ([c690e28](https://github.com/schiste/toolhub-evolved/commit/c690e28d731cc94db6ff42292326ddae56b762cd))
- split six more route families out of v1.py ([c4cee59](https://github.com/schiste/toolhub-evolved/commit/c4cee59cccfc878fc1816f92a18226c08e98141d))
- split /v1/me/ out of v1.py and reach shared helpers through the module ([341bcc0](https://github.com/schiste/toolhub-evolved/commit/341bcc0e275b18cfd5285a43eeb98f63f29c5bec))
- move the /v1/write/ bridge out of v1.py ([80f8464](https://github.com/schiste/toolhub-evolved/commit/80f84647d39f3cd06189e1c853e0c14f46ca8197))

### Maintenance

- restore the lint gate after splitting v1.py ([bdfe2b3](https://github.com/schiste/toolhub-evolved/commit/bdfe2b395153a0d540022466433398ee9d882469))

### Other

- Revert "perf: serve built static assets from memory instead of NFS" ([43975bd](https://github.com/schiste/toolhub-evolved/commit/43975bdc4c874d7b06a1490ab94d8d900d09b636))

## 2026-08-04

### Features

- ship person profiles and relationship claims ([d21de8d](https://github.com/schiste/toolhub-evolved/commit/d21de8dbc306e49a5541cf1a089f271a6542d096))
- give search, lists and filtered home a cache-first health score ([4437250](https://github.com/schiste/toolhub-evolved/commit/4437250cf67d3da664428dee7b85e8069eb928ce))
- ship health summaries with the signed-in tool list ([b6f4c97](https://github.com/schiste/toolhub-evolved/commit/b6f4c97874feed0aea3c5425d882f7866cc1c0d6))

### Fixes

- type claim request ownership guard ([9d0333f](https://github.com/schiste/toolhub-evolved/commit/9d0333febfa540c34c46149bfcf06532fb774e41))
- derive claim roles from proof methods ([37055f6](https://github.com/schiste/toolhub-evolved/commit/37055f6b95cfb3d68456aa5952946b0e9c35dc5b))
- isolate claim drawer request state ([17dd29a](https://github.com/schiste/toolhub-evolved/commit/17dd29a0d27fcdd4a6366b1ee141264477a0ebf1))
- harden people reconciliation invariants ([cc9c3a2](https://github.com/schiste/toolhub-evolved/commit/cc9c3a2cce470412c342ed9c74597d111bd51564))
- keep both maintainer count names in the card projection ([919bfcb](https://github.com/schiste/toolhub-evolved/commit/919bfcb88e2c79c5324f972a985a326fe43103eb))
- read the tool page health summary alongside the canonical record ([b146fc4](https://github.com/schiste/toolhub-evolved/commit/b146fc4cc2e1be9fa8f95eb2314fbb057d78e77d))
- trim the summary cache to fit instead of halving it ([811b12c](https://github.com/schiste/toolhub-evolved/commit/811b12c76d857962eba5adc08cb0c64de3d175cd))
- show cached health scores in the first render ([0aacb82](https://github.com/schiste/toolhub-evolved/commit/0aacb82cdac23e3176e8a219a000b34a9c86b0a9))

### Performance

- fetch the score popover breakdown after the route renders ([78d4fec](https://github.com/schiste/toolhub-evolved/commit/78d4fec00a1227857d6a37e1be583e73eafd3989))
- serve tool cards a projected summary instead of the whole record ([dfd8238](https://github.com/schiste/toolhub-evolved/commit/dfd8238e240fcf976869aa3155d060a4b7b529ee))

### Documentation

- document person identity and claim workflows ([b5d8ecd](https://github.com/schiste/toolhub-evolved/commit/b5d8ecd9196a73cec0a2b4e14cf99e60b3b27a3d))

### Refactoring

- make people the relationship authority ([ae10bf6](https://github.com/schiste/toolhub-evolved/commit/ae10bf6f85d7ea10432923cfc737dc0d9f040dfb))

## 2026-08-03

### Features

- move release notes to bottom toaster ([268d8c7](https://github.com/schiste/toolhub-evolved/commit/268d8c724e9fb644a7bd6dc5a3205dcfcc0ba4f8))
- add reviewed marketing release notes ([9878a87](https://github.com/schiste/toolhub-evolved/commit/9878a87a87597d4850a73f44a85f2dd40fe94cf0))
- add deploy changelog announcements ([8a5f07b](https://github.com/schiste/toolhub-evolved/commit/8a5f07b4b229167c816784252b464aba83d068d4))

### Fixes

- recover from a failed module load instead of showing a blank page ([d73086b](https://github.com/schiste/toolhub-evolved/commit/d73086bb7873b3390a4bb14be69cb6da82c43d30))
- preserve release notice state and content ([828438f](https://github.com/schiste/toolhub-evolved/commit/828438f06df265abea5f48da4c6974140ad23c8a))

### Performance

- compose the landing page into one request ([619e6b2](https://github.com/schiste/toolhub-evolved/commit/619e6b225378993073055c99e8c70bf167848b9f))
- keep the static prose pages out of the first paint ([ea81748](https://github.com/schiste/toolhub-evolved/commit/ea817485339251667b1e1a60cd6bf449c933ddba))

## 2026-08-01

### Features

- verify external toolinfo ownership ([ca2794d](https://github.com/schiste/toolhub-evolved/commit/ca2794dc527023da712e97cb43a51e6810c9988e))
- backfill public Toolforge maintainers ([bff01d9](https://github.com/schiste/toolhub-evolved/commit/bff01d95cd1c3b6b9b3ec8bc9c3cc0731b1f1906))
- review local catalog corrections ([1f56736](https://github.com/schiste/toolhub-evolved/commit/1f567369656a919e7b0e1019fb4eafb8506af8a9))
- cache validated tool icons locally ([296f502](https://github.com/schiste/toolhub-evolved/commit/296f502876defe143b9558f4b13830cdff4a24b9))
- validate catalog URLs out of band ([9bfe505](https://github.com/schiste/toolhub-evolved/commit/9bfe505ed3b3eb4c1480e4d1891859955f85e860))
- materialize local catalog provenance ([3e4be39](https://github.com/schiste/toolhub-evolved/commit/3e4be392c9d4b6b384f0888042cf3d416067696d))
- serve search from local data first on a cold query ([afd0780](https://github.com/schiste/toolhub-evolved/commit/afd0780af023d1ea8936d55ccb386c6c9be583f5))
- repair and audit graph enrichment ([f0c4188](https://github.com/schiste/toolhub-evolved/commit/f0c418874f802c1b35adb8acc9fc627186ae57f2))
- consume discovered graph metadata ([caf16e6](https://github.com/schiste/toolhub-evolved/commit/caf16e6611d2f56b5eadc1077f183678f72bd070))
- feed official metadata into graph enrichment ([9c58952](https://github.com/schiste/toolhub-evolved/commit/9c58952bb435a6abe9f2913aaa1d69264ee5c2c8))
- materialize graph facet enrichment ([4013a9f](https://github.com/schiste/toolhub-evolved/commit/4013a9febe691406d4181d4d8fdff295a854c710))
- expose platform graph grouping ([f47b0c4](https://github.com/schiste/toolhub-evolved/commit/f47b0c4a672af03cf0eaab872fbd4dd28c9ee75b))
- pull related graph nodes together ([5647210](https://github.com/schiste/toolhub-evolved/commit/564721028c91635af5bec3221ab29dfc157b1975))
- report graph facet coverage ([1150540](https://github.com/schiste/toolhub-evolved/commit/1150540871814576a050a4f275bb32c038fc74ed))
- personalize signed-in homepage ([56fb016](https://github.com/schiste/toolhub-evolved/commit/56fb0164bfd357e2dc1e81d41a19277d1e6e7abc))

### Fixes

- keep favorite activity private ([160da25](https://github.com/schiste/toolhub-evolved/commit/160da2510b6ef9e377229da62b9f30300fce603f))
- trust authenticated Toolforge membership ([486fcac](https://github.com/schiste/toolhub-evolved/commit/486fcac50ade384581e5cc1973753bd68ac2de46))
- clean polluted resolver identity data ([f5415e2](https://github.com/schiste/toolhub-evolved/commit/f5415e25a7500086bf5bd91c671be2333378dfaa))
- keep canonical authors out of account resolver ([1d7a342](https://github.com/schiste/toolhub-evolved/commit/1d7a3427f845ce9f53293dd377716095d417fafc))
- keep invalid icons from disabling cache jobs ([c01c406](https://github.com/schiste/toolhub-evolved/commit/c01c4060e81788aa6115bd07a0ebb07fab54db12))
- render cached personal home ([f360dd0](https://github.com/schiste/toolhub-evolved/commit/f360dd07a7ae271ba3cb03c6873335eb611bcec4))
- keep the resolver throttle protective ([51ca494](https://github.com/schiste/toolhub-evolved/commit/51ca494be555e8a2369fac5efb63a5c153621cbb))
- break the render loop that hammered /v1/me/tools/ ([1ac7d6e](https://github.com/schiste/toolhub-evolved/commit/1ac7d6eef586993b13b32130e7a12ca7bc60264e))
- throttle the expensive tool resolver per user ([24e114b](https://github.com/schiste/toolhub-evolved/commit/24e114bb5897b9413774208cf14bcab2b4b622a4))
- stop /v1/me/tools/ failing on a derived-index race ([8cd340d](https://github.com/schiste/toolhub-evolved/commit/8cd340d75a78b6de26669078e10497cf9fa51dc8))
- read a deploy step's real exit status, not its output ([a1a5843](https://github.com/schiste/toolhub-evolved/commit/a1a58436386aaaadf0d32fcf5ab7faf7b031f086))
- stop a bulk delete leaving stale rows in the session ([baa0f9e](https://github.com/schiste/toolhub-evolved/commit/baa0f9ef9731d87c8f1d49d91f5901c5fc9cb4fc))
- drain the person reconciliation queue ([5221e21](https://github.com/schiste/toolhub-evolved/commit/5221e21fa3ac789ecc0c756695174d97be61002a))
- take data migrations out of the webservice startup path ([7e6e4f4](https://github.com/schiste/toolhub-evolved/commit/7e6e4f4be7b6b43107587e5420aba7e9f553ad79))
- escape href in the button atoms ([2c8cd47](https://github.com/schiste/toolhub-evolved/commit/2c8cd471b58fef0be15ee2bd67463579fda80512))
- clarify crawler-owned tool edits ([36468d4](https://github.com/schiste/toolhub-evolved/commit/36468d4400f50dde6b48135c6fff9362f33e03e8))
- make write lifecycle diagnostics transparent ([48a2869](https://github.com/schiste/toolhub-evolved/commit/48a28692a4937f31dee391d2344bd1fad8334eff))
- protect official write diagnostics ([bc04b06](https://github.com/schiste/toolhub-evolved/commit/bc04b06395820a24d298dca2f4fa53ada3e4e098))
- guard official Toolhub write paths against scope escape ([fa84a4d](https://github.com/schiste/toolhub-evolved/commit/fa84a4d8908183a99d17963aeef3fd273f5c4ce7))
- merge graph project aliases ([668a82f](https://github.com/schiste/toolhub-evolved/commit/668a82fae0cc3658ab65526e4628791a37459fda))
- normalize graph grouping taxonomy ([6b9fd95](https://github.com/schiste/toolhub-evolved/commit/6b9fd95a7c2622c4c590eb6e183f905e6f4c4e2f))
- version derived graph cache schema ([ac48026](https://github.com/schiste/toolhub-evolved/commit/ac4802602cd536bce89cac4f1600032dfe096664))
- preserve rich graph catalog metadata ([221b714](https://github.com/schiste/toolhub-evolved/commit/221b714b55bfd360953f34849c5f8d42ff814d6a))

### Performance

- let the webservice serve more than four requests at once ([10b5929](https://github.com/schiste/toolhub-evolved/commit/10b5929d108ba33b2c2c7998124a61e06bd689fd))
- preload the whole first-paint module graph ([a6db733](https://github.com/schiste/toolhub-evolved/commit/a6db73379a0eb0b3d401a39e39889f06a637e79e))
- replace resolver throttle with per-user cache fill ([42ca94b](https://github.com/schiste/toolhub-evolved/commit/42ca94bafc06642fab506aad714e2dd45bbbc374))
- gzip the responses the edge leaves uncompressed ([ca8c017](https://github.com/schiste/toolhub-evolved/commit/ca8c017f59a7e716f4d16118711f6ea8845f3295))
- cache private user tool resolution ([8056694](https://github.com/schiste/toolhub-evolved/commit/805669415029912491d4f4777a41fee8fe094943))
- stop paying for round trips one at a time ([ec300a4](https://github.com/schiste/toolhub-evolved/commit/ec300a47d77ac2065c2265f77e9d94efab0ad6d3))
- filter and limit the canonical tool search in SQL ([8ad0c87](https://github.com/schiste/toolhub-evolved/commit/8ad0c875709355e41e29f8c3b701e30ceca990a7))
- let cached Toolhub reads stay fresh for longer than a minute ([8d511a8](https://github.com/schiste/toolhub-evolved/commit/8d511a81fe040593ee23a557e33f6286d4c90f1d))
- stop blocking the main thread on every API response ([e534899](https://github.com/schiste/toolhub-evolved/commit/e53489930ea580d3b7569eedf8adeeffb51d2649))
- never build a tool summary on the read path ([f5c6354](https://github.com/schiste/toolhub-evolved/commit/f5c6354967e679931b20a61db8406aec249b4407))
- invalidate the shared API cache in SQL ([25992f1](https://github.com/schiste/toolhub-evolved/commit/25992f1464fb465881464556ad05004feb6f8f8b))
- stop a cold membership cache blocking route render ([b3893c7](https://github.com/schiste/toolhub-evolved/commit/b3893c70a64dbce7f44bc2230e72d8ad811af119))
- persist list membership cache ([fb855c1](https://github.com/schiste/toolhub-evolved/commit/fb855c109e3dd8d3601cfa6d9edc2b4e1bca97d9))
- move large graph layout off main thread ([62b49b3](https://github.com/schiste/toolhub-evolved/commit/62b49b3e105d1bfe8e5d58e9123e2f6ac43161c1))
- cache and progressively load tool graph ([c37be2b](https://github.com/schiste/toolhub-evolved/commit/c37be2b3157af8a29dc974aed372d772ba832948))

### Interface and accessibility

- name the bodiless statuses in the compression guard ([038622b](https://github.com/schiste/toolhub-evolved/commit/038622bd6106ee74248936c7115ffe14f3483779))

### Documentation

- note which callers MAX_TOTAL_BYTES actually binds ([68a0d58](https://github.com/schiste/toolhub-evolved/commit/68a0d583e588700fc1fcdc38b499c3cb4681e160))
- record what actually bounds a repository checkout ([f238c29](https://github.com/schiste/toolhub-evolved/commit/f238c292395cf7dbfcde9139e7eb3cf6fa1d6925))

### Operations

- schedule catalog provenance maintenance ([b145a94](https://github.com/schiste/toolhub-evolved/commit/b145a9471c8b9d18b778d806fa467919bfcb5815))

### Refactoring

- preserve graph topology across facets ([3e51d85](https://github.com/schiste/toolhub-evolved/commit/3e51d8573e2c4125864ed895c4b9552cf76b94d5))

### Tests

- make async tool hydration route-aware ([962b5c8](https://github.com/schiste/toolhub-evolved/commit/962b5c854448aa204eb3ee5a49f8dfab318745f0))
- verify large graph worker in browser ([c67de0f](https://github.com/schiste/toolhub-evolved/commit/c67de0f1cbf2eea6c09afb4b79a6876687e6d3ac))
- verify graph layout and Toolforge budgets ([cd0d1fa](https://github.com/schiste/toolhub-evolved/commit/cd0d1fa8b7edfcd75b84d65a61d1aa670e40541e))

### Maintenance

- ignore Playwright MCP scratch output ([421a847](https://github.com/schiste/toolhub-evolved/commit/421a84778b405adbb73a5c8b6b181e8675fd0755))
- stop formatting local agent state ([c7488cc](https://github.com/schiste/toolhub-evolved/commit/c7488cc08795253619fecc05daffcf06a1df0d8d))
- spell-check the caching terms added to api.js ([16d29f2](https://github.com/schiste/toolhub-evolved/commit/16d29f24fcfbce5be4e733e9456a6ad68b6465f6))
- add a temporary probe for sizing ProxyFix ([0ce4fc1](https://github.com/schiste/toolhub-evolved/commit/0ce4fc119f141c2cd4a56dd35cc6100b04c62a02))

### Other

- Add three-failure job circuit breaker ([8ae1c44](https://github.com/schiste/toolhub-evolved/commit/8ae1c447bfe16e2bda685df81c86175943d41d25))
- Complete legacy catalog schema repair ([afc1038](https://github.com/schiste/toolhub-evolved/commit/afc103888943e572a6b59e902534456224ce76e5))
- Serialize maintainer reconciliation jobs ([74a3e46](https://github.com/schiste/toolhub-evolved/commit/74a3e46aa9ba38cb468d3ba516991bb107b60542))
- Repair scheduled job schema and scan failures ([79a9865](https://github.com/schiste/toolhub-evolved/commit/79a98652c11af862ebf002a4ddd313718c610979))
- Scale graph views and add grouping modes ([07fac13](https://github.com/schiste/toolhub-evolved/commit/07fac1305db988fc8364529e16ede06330a88b2d))

## 2026-07-31

### Features

- improve tool detail workflows ([e7cea92](https://github.com/schiste/toolhub-evolved/commit/e7cea92abd01467657efc9d995358be6dd8f08f9))
- route tool card interactions ([c0fe130](https://github.com/schiste/toolhub-evolved/commit/c0fe1302831ffaaa102d9889a8e80de170d55a5a))
- reconcile people after data ingestion ([7037bf7](https://github.com/schiste/toolhub-evolved/commit/7037bf7f5b0305051f4bf450d26ae3ab43ef7f7e))
- reconcile historical people deterministically ([c5c7679](https://github.com/schiste/toolhub-evolved/commit/c5c7679c04af94db5976c9e99319b4e4ab1b50d3))
- surface typed tool relationships ([2d555f7](https://github.com/schiste/toolhub-evolved/commit/2d555f7574426662a5a8a7fd418f9a263053b412))
- normalize people and tool relationships ([abcb4bf](https://github.com/schiste/toolhub-evolved/commit/abcb4bfd90b0c4ea7c4d0c319c225517fc7404e6))
- switch catalog sync to recent changes ([1ac76a4](https://github.com/schiste/toolhub-evolved/commit/1ac76a48ea96e8576f5b4f9b4d887778e400b206))
- synchronize full tool catalog ([595d805](https://github.com/schiste/toolhub-evolved/commit/595d805f779598934db2c1c9839466bac734090c))
- analyze tool repositories incrementally ([285931c](https://github.com/schiste/toolhub-evolved/commit/285931c30bc89b5bbd858a24999ed10fd025a99f))
- color tool cards by health grade ([48e0edd](https://github.com/schiste/toolhub-evolved/commit/48e0edd37175c5e505dc448e40f3c9a74af31ece))
- compact tool card signals ([b116736f](https://github.com/schiste/toolhub-evolved/commit/b116736f68d4405c0cda12e1813244e0032d05e4))

### Fixes

- unify tool page actions ([dd47f4e](https://github.com/schiste/toolhub-evolved/commit/dd47f4eaf380f5b1cab010680db33b6b2d9673db))
- resolve people through stable aliases ([28c9624](https://github.com/schiste/toolhub-evolved/commit/28c9624093dd52b094aa7d03d57b1b7d2a8e0efa))
- show all featured tools ([cc4daf9](https://github.com/schiste/toolhub-evolved/commit/cc4daf945f0198cc6b8d803c0d40dc9feed838fc))
- remove narrow prose cap from health score ([2e932bf](https://github.com/schiste/toolhub-evolved/commit/2e932bf286511645d18beab6b84d5414993b079f))
- widen table-heavy reference pages ([a73487f](https://github.com/schiste/toolhub-evolved/commit/a73487f23f30acc20b3cacbab264b174f5ebb534))

### Performance

- defer styleguide demo graph mount ([51ccae2](https://github.com/schiste/toolhub-evolved/commit/51ccae2d1b3a3cf326fafce430e752a864a185b9))
- defer styleguide token hydration ([8072f11](https://github.com/schiste/toolhub-evolved/commit/8072f11e2ca440ac5781d28f046616320dd54ca1))
- load route styles before view commit ([f2f30da](https://github.com/schiste/toolhub-evolved/commit/f2f30da117c8d4b6f8ad502bd65727384b3af90a))
- stabilize styleguide token galleries ([21ca56a](https://github.com/schiste/toolhub-evolved/commit/21ca56a62d07aaf5fb7c70d91f6fe9e4195547b0))
- reserve viewport for route loading ([9c19853](https://github.com/schiste/toolhub-evolved/commit/9c198536e7fa3e813d12aadefc595f2e0591b5dc))
- avoid styleguide reflow during load ([d86ec91](https://github.com/schiste/toolhub-evolved/commit/d86ec91b1cd31e935103f5bfac580dfaf0641342))
- prewarm derived endpoints on deploy ([9ee626f](https://github.com/schiste/toolhub-evolved/commit/9ee626fc5d04537ac698b5e571045e501789773b))
- cache derived public payloads ([a3d6757](https://github.com/schiste/toolhub-evolved/commit/a3d67576b8f5e9a9891d0300028273f4f4b21bf2))

### Interface and accessibility

- tighten tool card spacing ([a66fef8](https://github.com/schiste/toolhub-evolved/commit/a66fef8745e1c99e889e2e60a0cb7579a9032ffc))

### Documentation

- clarify catalog synchronization rules ([bfc4d92](https://github.com/schiste/toolhub-evolved/commit/bfc4d92a632e56b3f0a1352bb3efc88bf1d93061))

### Operations

- schedule incremental people reconciliation ([4d17487](https://github.com/schiste/toolhub-evolved/commit/4d174872958bdc707a1711dae7f1e22925e328ab))
- schedule people reconciliation ([e824054](https://github.com/schiste/toolhub-evolved/commit/e8240542716f22d459dcdeb20c879e599f11d8c6))

### Refactoring

- surface maintainer verification in card byline ([7f6a012](https://github.com/schiste/toolhub-evolved/commit/7f6a012dc923e50c41d606835d1da2b6e195ea44))
- move tool card metadata topline ([619e7bb](https://github.com/schiste/toolhub-evolved/commit/619e7bb412221461bc3a8ff366fde7bfbd4bc369))

### Tests

- isolate deferred tool view mounts ([4965019](https://github.com/schiste/toolhub-evolved/commit/4965019ba83af6281387cfb514849068f98304d2))

### Maintenance

- move map link to footer ([f553e30](https://github.com/schiste/toolhub-evolved/commit/f553e30553e55e09a9f0bd42611a7b81a8e386fb))
- sync extracted i18n catalog ([e89553e](https://github.com/schiste/toolhub-evolved/commit/e89553e39626d49b18fcd20c380227487e389cc6))

### Other

- Improve interactive tool map filtering ([4c16f1a](https://github.com/schiste/toolhub-evolved/commit/4c16f1a73bbb2af35f785a20c96bf0f167a25068))
- Improve graph map rendering and navigation ([d2f78ac](https://github.com/schiste/toolhub-evolved/commit/d2f78acb895995cfc550b5a006b7835798b7e16e))
- Align shared status and health badges ([5a69b59](https://github.com/schiste/toolhub-evolved/commit/5a69b59ffede61a3177c3eee167d4e71a2a08d76))
- Fix feeds page and RSS discovery ([a63eef8](https://github.com/schiste/toolhub-evolved/commit/a63eef8431f8e6d9b54b03bec1c6efe632580bf9))
- Rename unmaintained health label ([aae298d](https://github.com/schiste/toolhub-evolved/commit/aae298d691c96e425236a4978b236c06c0182dec))
- Add floating issue support trigger ([e003e4c](https://github.com/schiste/toolhub-evolved/commit/e003e4ca87c4ca24dfeb6cf37944454d93da262a))
- Add authenticated issue reporting drawer ([a7189ac](https://github.com/schiste/toolhub-evolved/commit/a7189ac8effde763913f7f09d478a662c30cca0e))

## 2026-07-30

### Features

- add scoped enrichment operator script ([5d09f8d](https://github.com/schiste/toolhub-evolved/commit/5d09f8d5b875486e5b4b7de780192611ecb88f92))
- add source and maintainer health APIs ([5c0a2bd](https://github.com/schiste/toolhub-evolved/commit/5c0a2bd48c2930c04ed326d206ce54bc3c9d9b3f))
- add source analysis workspace ([03a706d](https://github.com/schiste/toolhub-evolved/commit/03a706da3096e4cfc2b2890f8c657f2287aa8307))
- add deterministic source analyzer ([9f05602](https://github.com/schiste/toolhub-evolved/commit/9f05602637a15e26c47e75e4175ce0784de7b2f8))

### Fixes

- keep strongest maintainer claim edge ([2d2ab22](https://github.com/schiste/toolhub-evolved/commit/2d2ab223dd394166909cb0f2fa42153a2c5c2fed))

### Performance

- stabilize styleguide rendering ([0b12141](https://github.com/schiste/toolhub-evolved/commit/0b12141e1af4486f2f1c428ecc5ca693079b3308))
- defer health summary enrichment ([f24d2f6](https://github.com/schiste/toolhub-evolved/commit/f24d2f697220c0a1321c68d29143728bd0bfe21b))
- dedupe local search backend reads ([9be754d](https://github.com/schiste/toolhub-evolved/commit/9be754d186df9868939f21a031de0c5705ae1dcf))
- render crawler history asynchronously ([76c7944](https://github.com/schiste/toolhub-evolved/commit/76c79446a57db6bfccde8b13fd739f5a2b01a808))
- serve graph from cached local payload ([3b0baa2](https://github.com/schiste/toolhub-evolved/commit/3b0baa246306a7758f6fc6e35eeafe40080aa777))
- defer tool detail discovery ([44fa423](https://github.com/schiste/toolhub-evolved/commit/44fa42322a5964be91b3ccff36bb2edee6e063da))
- lazy-load api docs explorer ([7f9eb83](https://github.com/schiste/toolhub-evolved/commit/7f9eb8328a38e9299537c7f32bd429eefda7e170))
- split account nav data from workbench ([49e8ecd](https://github.com/schiste/toolhub-evolved/commit/49e8ecd5478fe4b1b90f853e6437fd0d50cd1f1e))
- stabilize shell hydration ([34fb1e3](https://github.com/schiste/toolhub-evolved/commit/34fb1e3aebb6025ab87431ccc9992c2833b96ab3))

### Documentation

- surface source and maintainer health signals ([17d8bd4](https://github.com/schiste/toolhub-evolved/commit/17d8bd4904496690ebb1ea377f44e7e50c8f04a9))

### Tests

- align async performance contracts ([5c2bdaf](https://github.com/schiste/toolhub-evolved/commit/5c2bdafbfc21bf648ee301925fee6a0a6f341edc))

### Other

- Clarify Evolved footer policy pages ([476b618](https://github.com/schiste/toolhub-evolved/commit/476b618dff5414988467d4d25f5802a341913dbd))
- Add RSS feeds page and endpoints ([d413c4a](https://github.com/schiste/toolhub-evolved/commit/d413c4a70efaeb65070022d81abb3ca2736ade8a))
- Document reproducible health score formula ([d2af263](https://github.com/schiste/toolhub-evolved/commit/d2af263ff9756751a9649508469597372d3ffb48))
- Explain health score calculations ([21a30dc](https://github.com/schiste/toolhub-evolved/commit/21a30dc22337e6f63c80ac739e0a5ee619156d09))
- Clarify tool freshness signals ([d757063](https://github.com/schiste/toolhub-evolved/commit/d757063e648fbdd4667a6bd82200588f3f44df0d))
- Add transparent health score tooltip ([e542402](https://github.com/schiste/toolhub-evolved/commit/e5424025517ca55d58fe151bfe587f6190812d64))
- Bound detail discovery before health render ([03bf034](https://github.com/schiste/toolhub-evolved/commit/03bf034871fca457178c29973c876a3d7e117380))
- Fix eager health summary rendering ([e4845cc](https://github.com/schiste/toolhub-evolved/commit/e4845cce6055bdd4e87cb63131c3a87fad4f2c0b))
- Fix Toolforge health summary query ([45dd269](https://github.com/schiste/toolhub-evolved/commit/45dd26937e0576eae65da7b6e5965321ed266def))
- Raise JS budget for health summaries ([4c5bdba](https://github.com/schiste/toolhub-evolved/commit/4c5bdbabf9281ba538064f04ad4ab9e82384857f))
- Surface health status with cache-first tool views ([30900fe](https://github.com/schiste/toolhub-evolved/commit/30900fef25096a7d4a731eff6b92893898288610))
- Add canonical Toolhub cache and health summaries ([46b3416](https://github.com/schiste/toolhub-evolved/commit/46b341614a4ce2e02fe0dc089837380b064fe184))

## 2026-07-29

### Features

- refine account workbench experience ([d027aea](https://github.com/schiste/toolhub-evolved/commit/d027aea8b1ea0f4126d60d95f68bda2bd22ec83d))
- merge tool registration into my tools ([3dba63d](https://github.com/schiste/toolhub-evolved/commit/3dba63d5ab0067c6917b0cf80208e19089d6b490))
- redesign account workspace pages ([6491831](https://github.com/schiste/toolhub-evolved/commit/64918317daf52a3e9ffacc2265dce2d1c9f6f9bc))
- add icon provenance fallbacks ([6ca30ce](https://github.com/schiste/toolhub-evolved/commit/6ca30ce33915a15c94654ee5cd7cb9cf2f92dbe5))
- add pseudolocale QA mode ([9988392](https://github.com/schiste/toolhub-evolved/commit/9988392a85f8f79de9438564734e95254936e4a8))
- make remaining UI surfaces i18n ready ([8854a1d](https://github.com/schiste/toolhub-evolved/commit/8854a1db2f05ae954c22851a0d3766fe51096edc))
- make frontend copy i18n ready ([7fbbc71](https://github.com/schiste/toolhub-evolved/commit/7fbbc71342ce5b5a936393d55ba31542ad04eb61))
- embed API explorer in docs page ([5ef8d54](https://github.com/schiste/toolhub-evolved/commit/5ef8d543712348f0b1c3cc9e83befde837b5b40c))
- add curated API explorer organism ([c94abe7](https://github.com/schiste/toolhub-evolved/commit/c94abe7a428ec02a49c8e47df9c33594e81d29b5))
- add accessible command palette and skeleton loading ([2d11a89](https://github.com/schiste/toolhub-evolved/commit/2d11a89bc893629f31f0df72b733c4ec1b23cdd0))

### Fixes

- consolidate my tools account navigation ([b9b1e6d](https://github.com/schiste/toolhub-evolved/commit/b9b1e6d902dde446c75e51fbfccb90cec5947878))
- tighten account tab layout ([b68b40a](https://github.com/schiste/toolhub-evolved/commit/b68b40a568092b3e9929484a39229bd6744d9720))
- keep account tabs before actions ([ba9a3b4](https://github.com/schiste/toolhub-evolved/commit/ba9a3b456d1b66f25edc3f318bc79d5f05d838a1))
- rebuild profile tab bar ([ad4fb24](https://github.com/schiste/toolhub-evolved/commit/ad4fb241dff9905474fb466fa6043ec3a1dc2874))
- polish profile workbench tabs ([5850f5d](https://github.com/schiste/toolhub-evolved/commit/5850f5db8901a8f9659094988c49db0a9971f81e))
- stabilize shell during reload ([7d5b073](https://github.com/schiste/toolhub-evolved/commit/7d5b073b08c35ddb468abd88a610c31bceb95209))
- remove decorative tool card search hint ([d1820ec](https://github.com/schiste/toolhub-evolved/commit/d1820ec92c52e3bfee4618d2c160773621006b71))
- render invalid outbound URLs defensively ([6fe2c00](https://github.com/schiste/toolhub-evolved/commit/6fe2c00732d52ba270023214fbc73f5e75c57ffe))
- drop the pre-encryption plaintext token path ([0b4317f](https://github.com/schiste/toolhub-evolved/commit/0b4317fc22d31e5deedd8291edab9a98872bcf6b))
- prevent API docs mobile overflow ([2d390fe](https://github.com/schiste/toolhub-evolved/commit/2d390feb25366f86231516467119f58d143d4cf1))
- treat split-horizon DNS as a deployment fact, not a policy choice ([235e35c](https://github.com/schiste/toolhub-evolved/commit/235e35c6a95c8e9dfaf53b49046796bdecb6bffd))
- keep account auth loading neutral ([cc56ea7](https://github.com/schiste/toolhub-evolved/commit/cc56ea700b8789010e601026c7051f03c1b576d5))
- avoid signed-out flash on protected routes ([39764f1](https://github.com/schiste/toolhub-evolved/commit/39764f1e32772631855fe00da48bb895e92faa7d))

### Documentation

- map i18n readiness work ([48c2694](https://github.com/schiste/toolhub-evolved/commit/48c26947ada0bc2775e150d699cca2f8e9016edf))
- surface the API explorer ([bc43855](https://github.com/schiste/toolhub-evolved/commit/bc438554b21770332bbb915eb282cffbe56791cb))

### Refactoring

- one policy-driven implementation for outbound fetches ([4ee7171](https://github.com/schiste/toolhub-evolved/commit/4ee71719e40ce9d5e0db06a7cc559a5a979658fd))

### Tests

- gate outbound fetches on going through backend.outbound ([fb56712](https://github.com/schiste/toolhub-evolved/commit/fb56712156312f20379ad2818d021bdf61a0fc94))

### Maintenance

- refresh js payload budget ([78ae677](https://github.com/schiste/toolhub-evolved/commit/78ae6778cec1a88f5b1e7920af7c63a40dd28283))
- support shell i18n extraction ([395fcdb](https://github.com/schiste/toolhub-evolved/commit/395fcdb146ad689416dfea3d6bd01d6af10c02ec))
- expose i18n catalog check ([3522543](https://github.com/schiste/toolhub-evolved/commit/35225437eba6cdfe505ad351166144a0d9761894))
- harden i18n source extraction ([c59d046](https://github.com/schiste/toolhub-evolved/commit/c59d046a835e972fe311363506aba18f2c742eb0))
- allow API explorer sample spelling ([9ab9402](https://github.com/schiste/toolhub-evolved/commit/9ab940209273fb727a850c93e0836b6aa5810063))

## 2026-07-28

### Features

- index official toolinfo sources ([d0e56ca](https://github.com/schiste/toolhub-evolved/commit/d0e56ca5fdcbd1422b5039b10e3e157a8f130fe0))
- show automated discovery status ([d2993b7](https://github.com/schiste/toolhub-evolved/commit/d2993b7a06cb346cb578be05e1021a54c2c6a160))
- automate toolinfo discovery ([67c79dc](https://github.com/schiste/toolhub-evolved/commit/67c79dcb8e50e6a48371b224708e4ee301cd8ef7))
- discover toolinfo urls from homepages ([4a3dab1](https://github.com/schiste/toolhub-evolved/commit/4a3dab15d7a24ac7d7cbc24f5419573f39def42b))
- polish recent activity and crawler history ([74ad071](https://github.com/schiste/toolhub-evolved/commit/74ad0711b042d8cc13c1328bee5f85d32cde4930))
- review changes before saving edits ([d33207b](https://github.com/schiste/toolhub-evolved/commit/d33207b9c6187b8a43e22a37a8d93ef2983cd4cf))
- add tool detail delete action ([fb51715](https://github.com/schiste/toolhub-evolved/commit/fb5171536178023c384698f9064e8101279abef1))
- add frontend and server timing diagnostics ([74b1e61](https://github.com/schiste/toolhub-evolved/commit/74b1e610f734bac9bbb1f4842d04f8361b70479a))
- encrypt stored Toolhub OAuth grants at rest ([8a37bb4](https://github.com/schiste/toolhub-evolved/commit/8a37bb4490362bab98821d14fd9853dac0e63885))

### Fixes

- prioritize official my-tools metadata evidence ([6dc8ce1](https://github.com/schiste/toolhub-evolved/commit/6dc8ce1044043c433356e835f844d8353ab5848b))
- follow safe official source redirects ([18f4f46](https://github.com/schiste/toolhub-evolved/commit/18f4f46f70dd89faf77f841aa11028a235e21f7e))
- allow official Toolforge crawler sources ([9f6e539](https://github.com/schiste/toolhub-evolved/commit/9f6e5395dca0e656ae7b3fe802e3489cf400f980))
- log why an OAuth sign-in failed ([944ba6b](https://github.com/schiste/toolhub-evolved/commit/944ba6b0d09208f0a791e0e0dbdf1ad0d0a6e93f))
- polish startup shell and feature status ([f97686d](https://github.com/schiste/toolhub-evolved/commit/f97686dba84cba6a01adf7f3aa4b1116107dd05c))
- show field errors for URL write validation ([0ccf5e9](https://github.com/schiste/toolhub-evolved/commit/0ccf5e99604c84b74e749031bbf1c79ce87cbf29))
- render api field language metadata ([43f0663](https://github.com/schiste/toolhub-evolved/commit/43f066359001fa316c443dbacd0fd03c73cabfb1))
- explain crawled tool authorship editing ([6232df1](https://github.com/schiste/toolhub-evolved/commit/6232df1c796283bea13b969f4c29c177e5a4397c))
- lock the rolling rate limiter ([aea8aeb](https://github.com/schiste/toolhub-evolved/commit/aea8aeb9bb56f07d9dd44fbf8189601a01e8573e))
- evict expired tool-owner cache rows ([e435394](https://github.com/schiste/toolhub-evolved/commit/e435394e93237590cbeab6ddde3d2930787a6cad))
- bound the /v1/recent/owners/ upstream fan-out ([2a32a06](https://github.com/schiste/toolhub-evolved/commit/2a32a063de1f558269bfcb6af09913eb56833af8))
- harden ToolsDB backup script ([90a30c7](https://github.com/schiste/toolhub-evolved/commit/90a30c72905de443e09e34dac31b58925f4447b0))
- rate-limit anonymous reads through the API proxy ([d64ec17](https://github.com/schiste/toolhub-evolved/commit/d64ec17035293b703193622100cc873fe51afd69))
- reject parent-directory segments in proxied API paths ([2a346b3](https://github.com/schiste/toolhub-evolved/commit/2a346b386fdf929179bbbecd70497779c3d2c6a5))
- query Toolforge membership over LDAPS ([ef6fe48](https://github.com/schiste/toolhub-evolved/commit/ef6fe48d683b8102762c419f1d5f33cf57266450))
- make sign-out a CSRF-protected POST ([d4e7bdd](https://github.com/schiste/toolhub-evolved/commit/d4e7bdddf410c91b81f6ac232be2a0e394ad51d2))
- revoke sessions server-side on sign-out ([857645d](https://github.com/schiste/toolhub-evolved/commit/857645d0bb365735611c431199a330bc399688ec))
- pin the OAuth callback to the configured base URL ([a04de83](https://github.com/schiste/toolhub-evolved/commit/a04de83cda2062785993eb0582c9524364de3e47))
- refuse to start without a session secret ([5d54dd0](https://github.com/schiste/toolhub-evolved/commit/5d54dd0910ab803ed3d38d3fa17ca1cfbadc23a9))

### Performance

- split frontend startup routes ([daab152](https://github.com/schiste/toolhub-evolved/commit/daab15229d506da6e317b11d9dee63fb531664a3))
- warm deploy cache and bulk recent owners ([8bd3ff7](https://github.com/schiste/toolhub-evolved/commit/8bd3ff76eac1f2255903c65494ad83a597ffb0af))
- prewarm hot Toolhub API cache ([fa81d7c](https://github.com/schiste/toolhub-evolved/commit/fa81d7cc34c26167d5db7f497a795c0a41f82be4))
- move recent invalidation to scheduled job ([fa6d505](https://github.com/schiste/toolhub-evolved/commit/fa6d5054b447a23094b44a0987a9f55c878291b3))
- serve stale API cache while refreshing ([c665e17](https://github.com/schiste/toolhub-evolved/commit/c665e17252be041567d96d7ac246145f5f6392ea))
- render app shell before boot fetches ([e52a114](https://github.com/schiste/toolhub-evolved/commit/e52a114433b52c5926ef83cda5745fa95ae01b8e))

### Interface and accessibility

- clear ruff findings in the proxy ([e558e46](https://github.com/schiste/toolhub-evolved/commit/e558e462e84b95feb567d87730f1cacd5121a360))

### Documentation

- complete deployed feature inventory ([28cd5a5](https://github.com/schiste/toolhub-evolved/commit/28cd5a56dd3e5aee918da28953a1b045b3bafc16))
- document revision diff operations ([3445080](https://github.com/schiste/toolhub-evolved/commit/3445080526386f740e0cd5d1a01920f0e0d29b6a))
- publish toolinfo schema guidance ([fbccb52](https://github.com/schiste/toolhub-evolved/commit/fbccb529b8b7a673477c3865cfae052abadb0229))
- note where the media POST guard is applied ([1829691](https://github.com/schiste/toolhub-evolved/commit/1829691d935c6e9c2f334267b82c6dda4115d18d))

### Refactoring

- share write lifecycle helpers ([b3aa6b8](https://github.com/schiste/toolhub-evolved/commit/b3aa6b8d47bc1676bf257e86eddd008f95b5c27a))

### Tests

- add rtl layout guard ([c93e73e](https://github.com/schiste/toolhub-evolved/commit/c93e73e5503d0730d9c10754e3b9d9c0a11e3782))
- gate every /v1 route on having an auth guard ([fadeaa5](https://github.com/schiste/toolhub-evolved/commit/fadeaa584d63aaf5ee8cd5d83f28a806960c1913))
- restore the 100% proxy coverage gate ([8d69ff6](https://github.com/schiste/toolhub-evolved/commit/8d69ff666bc45b25e1f78d94810b313bb36966af))
- restore the 100% proxy coverage gate ([994b21a](https://github.com/schiste/toolhub-evolved/commit/994b21a566b95598da1f57fd62f4612fe2aa95f8))

### Maintenance

- refresh i18n catalog ([b3ce58a](https://github.com/schiste/toolhub-evolved/commit/b3ce58a7dc81495d8f12fded97a762695fa95689))
- speed up automated toolinfo discovery ([ebc5a9f](https://github.com/schiste/toolhub-evolved/commit/ebc5a9f2b8a63f4d82e882764a068219eea708ec))
- align js coverage gate with current suite ([c79f480](https://github.com/schiste/toolhub-evolved/commit/c79f480bfb7866766f13ef09475b5b5c7b6bec95))
- scope js payload budget to user routes ([42648d0](https://github.com/schiste/toolhub-evolved/commit/42648d0bc902ab68c872a0d89a79723b11431367))
- update spellcheck dictionary ([86b54a5](https://github.com/schiste/toolhub-evolved/commit/86b54a5dfa1575a7e73c7d52a7928b884b472347))
- type author verification fields ([1130b19](https://github.com/schiste/toolhub-evolved/commit/1130b19cc1fdbcbe22ce1a2d68f6e89d877e058e))
- release 0.2.0 changelog ([5d3e52f](https://github.com/schiste/toolhub-evolved/commit/5d3e52fbea3f4c0636c426bcedac011cc67ba399))
- clear high-severity dev-chain advisories ([1dcf832](https://github.com/schiste/toolhub-evolved/commit/1dcf832bc2764434a516d50ff9428f6295fb64ea))
- require cryptography 48.0.1 for GHSA-537c-gmf6-5ccf ([69e17a0](https://github.com/schiste/toolhub-evolved/commit/69e17a088080204cb341468eca474c88a8863bb9))

## 2026-07-27

### Features

- discover my tools from Toolforge membership ([29134d2](https://github.com/schiste/toolhub-evolved/commit/29134d2698377028af4a0572a71341b6f276ec1e))
- show per-tool authorship verification UI ([ee672d1](https://github.com/schiste/toolhub-evolved/commit/ee672d1712fd3b65146576e04d7f1ac71fdadca7))
- add per-tool author provenance backend ([acffd45](https://github.com/schiste/toolhub-evolved/commit/acffd456da931d8f2bf5013bec27b72f4e94d1fb))

### Fixes

- require stable session secret in production ([bfb2a47](https://github.com/schiste/toolhub-evolved/commit/bfb2a4772c5e8e7c479e051f5722c1032e663b6e))
- parse Toolsadmin maintainer tables ([5db9e69](https://github.com/schiste/toolhub-evolved/commit/5db9e6956a299bf3fc6642a397647b97fc18f052))
- bound the in-memory write rate-limit table ([25e1a7a](https://github.com/schiste/toolhub-evolved/commit/25e1a7a2b368150981047c7b733f94cac3d3d693))
- compare CSRF tokens in constant time ([c8e5551](https://github.com/schiste/toolhub-evolved/commit/c8e5551dbb3b663bb9d072fa236f9933b808e22e))
- clarify my tools provenance copy ([3683a28](https://github.com/schiste/toolhub-evolved/commit/3683a288fc88a2db05fab830ce49dcffd90c694d))

### Documentation

- refresh hybrid plan user-facing copy ([e2d5960](https://github.com/schiste/toolhub-evolved/commit/e2d59607e03d94e68ee45babbf0a634a107732e2))
- document hybrid authorship policy ([f680114](https://github.com/schiste/toolhub-evolved/commit/f68011402b2adfc4348a2bbafba95ee939e3492d))

### Tests

- cover active rate-limit pruning ([9b38ccf](https://github.com/schiste/toolhub-evolved/commit/9b38ccfe1d323d6a3decd8d238aa898fc8f840ec))

### Other

- Add owned tools account page ([f284ae8](https://github.com/schiste/toolhub-evolved/commit/f284ae83c864568f66e164f75e398fa9d33a9e65))
- Add developer profile pages ([de01651](https://github.com/schiste/toolhub-evolved/commit/de01651112f23685a0fb3e5c6de9fb5e348160d8))
- Document hybrid cache operations ([27df51c](https://github.com/schiste/toolhub-evolved/commit/27df51c60a7f44cda4e8762d41c8ad593c817fd5))
- Enrich recent owners progressively ([b04dce6](https://github.com/schiste/toolhub-evolved/commit/b04dce66c120f99c83b9f8493be6d8425e1b4601))
- Make public API reads feel instant ([1914ba6](https://github.com/schiste/toolhub-evolved/commit/1914ba61afe60d6439f655285255f4bc10c29333))
- Improve Toolhub API cache lifecycle ([7cce203](https://github.com/schiste/toolhub-evolved/commit/7cce203ee0b5ff0ac94c23e7720792ae0602039c))
- Persist anonymous Toolhub API cache ([2c7e42c](https://github.com/schiste/toolhub-evolved/commit/2c7e42c15a32739bf862df3715eb64f56ad00c82))
- Reduce production module load failures ([bb246a8](https://github.com/schiste/toolhub-evolved/commit/bb246a862a82c481afffd58db74dbea92bef3d90))
- Cache versioned production assets ([eb6c7f0](https://github.com/schiste/toolhub-evolved/commit/eb6c7f0f3c819257fbca4d57fb3298b58291f65f))
- Make sitenotice more compact ([1c3d0bc](https://github.com/schiste/toolhub-evolved/commit/1c3d0bce568c070dfcf0eee836046c8247ee975b))
- Collapse recent comments by default ([e5efed8](https://github.com/schiste/toolhub-evolved/commit/e5efed835e77606d52f40137f1e1d92ae2ce5848))
- Align recent table layout with design system ([2d633e3](https://github.com/schiste/toolhub-evolved/commit/2d633e3fd31eebe452bf4b1f9921297509a24056))
- Convert recent changes to sortable table ([b5e6a14](https://github.com/schiste/toolhub-evolved/commit/b5e6a14ef9790a7359070e2f4f737025ec208e04))
- Upgrade recent changes page ([55099dc](https://github.com/schiste/toolhub-evolved/commit/55099dce5c0d27e9c52f4ebbe11105ed57fad49c))
- Document hybrid issue hygiene ([b2bc376](https://github.com/schiste/toolhub-evolved/commit/b2bc376ccc748e12e820ce2ef4152cdb03a83ceb))
- Add shared sync status UI contract ([c4fa13e](https://github.com/schiste/toolhub-evolved/commit/c4fa13e5930c37a9b66ec71cfd226494628d389b))
- Add Evolved public data moderation controls ([bb77918](https://github.com/schiste/toolhub-evolved/commit/bb77918baeebdc15205d5d0c8a11b0b3c6fd9444))
- Wire frontend to official-first write lifecycle ([b3b88ee](https://github.com/schiste/toolhub-evolved/commit/b3b88ee9a86b91a0f249af460f1b0c75cc0f8c81))
- Add official-first write lifecycle ([8f6327d](https://github.com/schiste/toolhub-evolved/commit/8f6327d935d79467ecd23ecf163e2108e1a9b165))
- Capture Toolhub validation metadata ([68a2182](https://github.com/schiste/toolhub-evolved/commit/68a21825543660546cffb5762edaa6862b8ab061))
- Document shared provenance contract ([7b152fe](https://github.com/schiste/toolhub-evolved/commit/7b152fe73d13e61f6591722df945b9bdd3ff48a3))
- Keep Toolhub reads canonical in the frontend ([6c88b3f](https://github.com/schiste/toolhub-evolved/commit/6c88b3f21f3f4bc06739f4be4e5033d00082285c))
- Add shared provenance lifecycle model ([09e274b](https://github.com/schiste/toolhub-evolved/commit/09e274b580b5ad18cdb90dbdd792175170d409e2))
- Document Evolved authorization foundation ([72fdf4c](https://github.com/schiste/toolhub-evolved/commit/72fdf4cd7e00bbc5ed21a7764b07fc0fe48789f0))
- Enforce Evolved authorization on local writes ([19531ea](https://github.com/schiste/toolhub-evolved/commit/19531ea9aafd95988b9d39db69ef1066fab04654))
- Add Evolved-local authorization roles ([70ab4a2](https://github.com/schiste/toolhub-evolved/commit/70ab4a22b45f6e8d2da3fe591302ca0bea467364))
- Bump knip from 5.88.1 to 6.29.0 (#98) ([fd63015](https://github.com/schiste/toolhub-evolved/commit/fd630155deead6f9f469eb6d9ec32e4a9b29ba08))
- Bump stylelint from 16.26.1 to 17.14.0 (#96) ([37eae39](https://github.com/schiste/toolhub-evolved/commit/37eae390f5f6203dee23f5db9807d373cc67a576))
- Bump globals from 16.5.0 to 17.7.0 (#97) ([bd60a5b](https://github.com/schiste/toolhub-evolved/commit/bd60a5b6f67056890c7778c5dedcd834420ede26))
- Bump @commitlint/config-conventional from 21.1.0 to 21.2.0 (#94) ([8c30c49](https://github.com/schiste/toolhub-evolved/commit/8c30c4943d47a5ab221c086220a418780eb8afa4))
- Bump actions/setup-node from 6 to 7 (#99) ([7c2f8bb](https://github.com/schiste/toolhub-evolved/commit/7c2f8bb7f95ded343e7c3f269c51c815b21f6968))
- Bump actions/setup-python from 6 to 7 (#100) ([bc6603f](https://github.com/schiste/toolhub-evolved/commit/bc6603f4f26844a2e568e3d99ba8bf3f3a7bd047))
- Remove Evolved feature toggle ([60fbda3](https://github.com/schiste/toolhub-evolved/commit/60fbda3cb790e3cc9528e10310bd5fc466994387))

## 2026-07-26

### Other

- Implement production hybrid Evolved features ([57c265e](https://github.com/schiste/toolhub-evolved/commit/57c265e3e7aad3e9b702249b5824e7e3894c2fe7))
- Plan clean production data removal ([e325317](https://github.com/schiste/toolhub-evolved/commit/e325317c624df959fa5843726f4ab115ad6fc280))
- Document hybrid feature realization plan ([2716217](https://github.com/schiste/toolhub-evolved/commit/2716217b6ea657dfc3fac3dde7d0d9cf6d478dda))
- Update Evolved feature status copy ([08b2f47](https://github.com/schiste/toolhub-evolved/commit/08b2f47d04b8cb328b5383a5a59ab258941ed2de))
- Raise coverage for CI gate ([b3fa1df](https://github.com/schiste/toolhub-evolved/commit/b3fa1df83e814a1b87c75b44af62e83f0395cd50))
- Share backend error formatting ([d4f1c43](https://github.com/schiste/toolhub-evolved/commit/d4f1c4392acd8258e479b9e3e0e4c25bf0430a76))
- Fix Wikimedia wiki target spelling checks ([107e5d4](https://github.com/schiste/toolhub-evolved/commit/107e5d4646537ba265e2a18f3578c52e40dc8e60))
- Add feature docs freshness pre-push check ([381e002](https://github.com/schiste/toolhub-evolved/commit/381e0029b224297c5ae28f5bca5ed0196f7e3cc3))
- Close Toolhub write workflow gaps ([136e7c4](https://github.com/schiste/toolhub-evolved/commit/136e7c488472ed179fec725e38708b92b89614a1))
- Implement Toolhub OAuth write-through ([3186b09](https://github.com/schiste/toolhub-evolved/commit/3186b09653eac9cbacd8c4db8f3c23fa9ee4f578))

## 2026-07-25

### Other

- Merge pull request #101 from schiste/claude/production-deployment-plan-j916b6 ([e9ef15d](https://github.com/schiste/toolhub-evolved/commit/e9ef15dc1f1634b04d715d191cc0ec56d37b4e8d))
- Address review: ownership, SSRF, validation, deploy deps, federation ([32d5294](https://github.com/schiste/toolhub-evolved/commit/32d529401dda492ab7d63161ac2367403e972244))
- finish tool/toolforms extraction; generate en.json catalog ([e0de9b3](https://github.com/schiste/toolhub-evolved/commit/e0de9b322b4d256f19b18682072ccc97af4b2e6d))
- extract chrome strings in tool and experiments views (in progress) ([7a71645](https://github.com/schiste/toolhub-evolved/commit/7a71645f7f9ed8fb06cbfa30c77487df2fd60752))
- complete router and static view extraction ([433c37c](https://github.com/schiste/toolhub-evolved/commit/433c37c54bb4242d3a162b03c46c054accb20e27))
- extract chrome strings in router and static views (in progress) ([9b486f2](https://github.com/schiste/toolhub-evolved/commit/9b486f2cb08c0fe66413901b887999999a3c6c92))
- extract chrome strings in search, lists and parity views ([654d173](https://github.com/schiste/toolhub-evolved/commit/654d173a3f42b172e80ab379ae7821ff79a420ee))
- extract chrome strings in atoms and core helpers ([6f96257](https://github.com/schiste/toolhub-evolved/commit/6f962570f85ec382af573107b59b48b72d9d26a7))
- extract chrome strings in organisms and molecules ([59eb0da](https://github.com/schiste/toolhub-evolved/commit/59eb0dac9e1a6decab8b099da1ded8a760e42f80))
- extract chrome strings in home, authors and graph views ([c223cba](https://github.com/schiste/toolhub-evolved/commit/c223cba80cce36e9a07ad42d99f6b0664dfb88f5))
- Document the implemented production architecture in the docs ([eb680df](https://github.com/schiste/toolhub-evolved/commit/eb680df306f5cc7936077641638e67426fb58227))
- Add i18n message catalog: t(), locale switching, en.json extractor ([360a8d7](https://github.com/schiste/toolhub-evolved/commit/360a8d75a49859f16a41fa17da3b101f180fac5e))
- Wire the SPA to the backend: real sign-in and write-through overlay sync ([86edac8](https://github.com/schiste/toolhub-evolved/commit/86edac8200008d0a3e657e443a87777a3e1fd596))
- Add production ops: Jobs-framework schedule, DB backup, runbook ([c86bc13](https://github.com/schiste/toolhub-evolved/commit/c86bc1320332ceeab8b142e27f2c3eb6134b397b))
- Add /v1 backend: project DB, Wikimedia OAuth, overlay API, crawler ([c240d8a](https://github.com/schiste/toolhub-evolved/commit/c240d8ae33b5abd1adbf0edd324c260f24e12ea5))
- Codify data architecture: live API + complementary project DB ([efdc711](https://github.com/schiste/toolhub-evolved/commit/efdc7115a09302bc6029b5ac7e621a4b197a7bf8))
- Add production plan: standalone product on Toolforge ([4f52b1e](https://github.com/schiste/toolhub-evolved/commit/4f52b1e887a027ec40fd3383096599a52742d019))

## 2026-06-27

### Other

- Upgrade to ESLint 10 via eslint-plugin-import-x; adopt its new checks ([dd3190f](https://github.com/schiste/toolhub-evolved/commit/dd3190fee6b58d6a901b8c92556f964c1fd86b98))
- Bump GitHub Actions: checkout v4→v7, setup-node v4→v6, setup-python v5→v6 ([f92272e](https://github.com/schiste/toolhub-evolved/commit/f92272e19a6068c25883b6a1d1d6940c8db99db6))
- Bump proxy minimums: Flask>=3.1.3, requests>=2.34.2 ([94fef50](https://github.com/schiste/toolhub-evolved/commit/94fef50ed61a845fa5aef280a870875b9529f751))
- Bump TypeScript 5.9.3→6.0.3 and jscpd 4.2.5→5.0.11 ([fbf8f42](https://github.com/schiste/toolhub-evolved/commit/fbf8f42e467f87687afef88585d0297b507d8fd8))
- Minify served assets on deploy (pure-Python, fail-safe) ([5f8cef0](https://github.com/schiste/toolhub-evolved/commit/5f8cef0139da8c33551d7a5c7cc385b1a40c0778))
- Lazy-load heavy routes + modulepreload the core chain ([fe3da41](https://github.com/schiste/toolhub-evolved/commit/fe3da41198b44dc05b67759215ccc6d5ba63e00f))
- Fix home.js document-listener leak on re-mount ([a9940d0](https://github.com/schiste/toolhub-evolved/commit/a9940d070192c756cb10bf787adbf7ebbaef4b28))
- Proxy: pool the upstream connection + cache hot GETs ([c8348f6](https://github.com/schiste/toolhub-evolved/commit/c8348f6e06056b859e3b27841ce6dd3000a282f7))
- Reduce cognitive complexity of the two worst route/view dispatchers ([19c07f0](https://github.com/schiste/toolhub-evolved/commit/19c07f021cbc862cdfa4b710f719276f1bc4683b))
- Test i18n under non-en locales (few/many plurals, locale formatting) ([7a09eed](https://github.com/schiste/toolhub-evolved/commit/7a09eede259e09a394dbf9479776651c59817ac6))
- Enforce types at the domain boundary (strict mode made real) ([a9158f5](https://github.com/schiste/toolhub-evolved/commit/a9158f5c3d7a253c7cf44189f357cdcaa6a4788d))
- Make outage failures honest instead of 'not found' / empty (literal 100%) ([216dc3c](https://github.com/schiste/toolhub-evolved/commit/216dc3c457f68b0032b245dfbb9fd75c798cd377))
- Ignore .coverage data file (proxy coverage gate) ([ace421e](https://github.com/schiste/toolhub-evolved/commit/ace421e385b286b736995d534ccfc4f6dc9aeb58))
- Harden + fully test the proxy (close the one untested boundary) ([d82318b](https://github.com/schiste/toolhub-evolved/commit/d82318b1180249d49a8c1eded6819c7550ab8134))
- Isolate quickview into its own mutation shard (fix runner OOM) ([01b44fb](https://github.com/schiste/toolhub-evolved/commit/01b44fb8d21e754e8ff7f8416ef293771101e3ae))
- Run organisms-rest single-worker too (fix runner OOM) ([ca8817f](https://github.com/schiste/toolhub-evolved/commit/ca8817f57d288c21fcd9bd87f12c1a0f9bef0bf3))
- Split force-graph into its own mutation shard (fix runner OOM) ([1e1ed71](https://github.com/schiste/toolhub-evolved/commit/1e1ed718b645aa268f907c9538385514b445a0fe))
- Remove unreachable try/catch in normalizeVcsUrl (core mutation 100%) ([1c2b452](https://github.com/schiste/toolhub-evolved/commit/1c2b452dc2e937260bcbec63bbfcad66eecd972d))
- Shard the mutation workflow into a per-area matrix ([4d1a794](https://github.com/schiste/toolhub-evolved/commit/4d1a7947616f4066de76e2ee7d918332e5caafeb))

## 2026-06-26

### Other

- Phase 4: coverage gate, break:100, finalize (whole app S-tier) ([5781ce5](https://github.com/schiste/toolhub-evolved/commit/5781ce5dd11023fb5086873aeb6882d15a1daadb))
- Phase 3d: views + main.js to 100% mutation (whole app at 100%) ([ad78731](https://github.com/schiste/toolhub-evolved/commit/ad787318cd29aec494453374bf8f47ca41513a5a))
- Move Stryker mutation to its own scheduled workflow ([3d484a8](https://github.com/schiste/toolhub-evolved/commit/3d484a846d187310ab07229c9fbeae4b1de0f2ac))
- Phase 3b+3c: atoms, molecules, organisms + graph.js to 100% mutation ([c581039](https://github.com/schiste/toolhub-evolved/commit/c5810390860b32238c0b2c0380d5cb78743cd2f2))
- Fix cspell: reword EQUIVALENTS.md to drop a camelCase fragment ([779cad2](https://github.com/schiste/toolhub-evolved/commit/779cad2bee680441fd7b8a817ff00b41e15ac010))
- Phase 3a: core mutation 23% -> 97% (13/14 modules at 100%) ([885d7db](https://github.com/schiste/toolhub-evolved/commit/885d7db68a809757bc7dd1affed7e5f8dd1e8bf0))
- Foundation: migrate unit tests to Vitest + happy-dom ([d4c2c8b](https://github.com/schiste/toolhub-evolved/commit/d4c2c8bdb6f3e238052243434ca9c09e452f1b25))
- Phase 2: enable full tsc strict mode across the app ([7139ec0](https://github.com/schiste/toolhub-evolved/commit/7139ec0026243bc8303ecb7115b6364191995f58))
- Phase 1: add CSP + security headers to the proxy ([28c09de](https://github.com/schiste/toolhub-evolved/commit/28c09de9eaf378d8d0a4b019e52f5ba7fdbf7599))
- Phase 0: silence ruff config warnings, pin deps, add Dependabot ([279505c](https://github.com/schiste/toolhub-evolved/commit/279505c2198b60da74e3d429b9e3ca70edebdb8d))
- Deduplicate espree parse boilerplate in checks.mjs ([9beb7c9](https://github.com/schiste/toolhub-evolved/commit/9beb7c952fbed6a15e848a874d55b1b3606a3239))
- Add fixed JS payload budget; fix main.js coverage + cspell ([2b25d50](https://github.com/schiste/toolhub-evolved/commit/2b25d50317b2890395397e572790ca62e7c3e883))
- Add HTML tag-balance check; fix unclosed div in search view ([75b0499](https://github.com/schiste/toolhub-evolved/commit/75b04990f6045fc380b821b4f41edffb73ef5e13))
- Add floating-promise check for the data-fetch API ([3a5f4cb](https://github.com/schiste/toolhub-evolved/commit/3a5f4cbdfe3fe84c4a2872b5de00208bd71d392b))
- Complete spacing/gap token-drift enforcement ([7cf17bf](https://github.com/schiste/toolhub-evolved/commit/7cf17bfc26f3efedeeeeb2c3b7fefc1213a217ae))
- Document ruff S-rules as the Python security gate ([c024ea9](https://github.com/schiste/toolhub-evolved/commit/c024ea99613c0a00112554a16240b886985a3147))
- Add gitleaks secret scan as a CI gate ([a97e46a](https://github.com/schiste/toolhub-evolved/commit/a97e46a9b66cf040e542ba5dd5f01e5f9f2ec735))
- Add commented-out-code detector to checks.mjs ([2368819](https://github.com/schiste/toolhub-evolved/commit/23688198d83ed4c9ea2dbbdfc2717d672492519a))
- Add static a11y template lint to checks.mjs ([76fe16d](https://github.com/schiste/toolhub-evolved/commit/76fe16d2049f42791e174a1cd538604bfedf5b94))
- Align official Toolhub route parity ([8ba1912](https://github.com/schiste/toolhub-evolved/commit/8ba1912112dcdf092f8afb450fe339300a8fe883))
- Add cspell spell-check gate with project dictionary ([4a64924](https://github.com/schiste/toolhub-evolved/commit/4a64924209c92e2b2d0a7937cf66017d95b98165))
- Widen tsc --checkJs gate to the whole app ([8b46df8](https://github.com/schiste/toolhub-evolved/commit/8b46df8b617b0e55555fe7d4303d9fbcbbc252c3))
- Fix dead arg in author link; type DOM accessors ([5068d6a](https://github.com/schiste/toolhub-evolved/commit/5068d6a8c1d372491a9ff884074bd96adf5c5efb))
- Add an unescaped-interpolation (XSS) check ([d38c861](https://github.com/schiste/toolhub-evolved/commit/d38c86100fc880cfb64291f4297583e5aad15efb))

## 2026-06-25

### Other

- Retry transient API failures with backoff ([7771ba9](https://github.com/schiste/toolhub-evolved/commit/7771ba90baf32ea87b269f84dcac0df4666bfa44))
- Make pre-commit hook executable ([9fa2713](https://github.com/schiste/toolhub-evolved/commit/9fa271312bc278791768ea1ffffdcd586fa9935e))
- Replace bespoke quality gate with standard tools and CI ([75b3efc](https://github.com/schiste/toolhub-evolved/commit/75b3efcc0a2a8ab4371794c43d8fe315afc030a1))
- Add CI workflow and revert no-store cache header ([e0067e6](https://github.com/schiste/toolhub-evolved/commit/e0067e60c0e76ad53d790cae28b562e62abd2b05))
- Replace gate scope-exclusions with real fixes ([6c092fd](https://github.com/schiste/toolhub-evolved/commit/6c092fdc2fb6a9506ab46ca8187c3b0eb214bf93))
- Serve SPA source with no-store to prevent stale-module breakage ([2f5e089](https://github.com/schiste/toolhub-evolved/commit/2f5e089071fa8a842b68a66c46611116e427555f))
- Replay static gates per commit in pre-push ([9f85b60](https://github.com/schiste/toolhub-evolved/commit/9f85b60675985fc2fbf4befa4968aab7d8d18d50))
- Add accessibility interaction tests ([02dc2ab](https://github.com/schiste/toolhub-evolved/commit/02dc2ab21da0b5cd5d8b9f9b0e02ebe9d1e6ca8b))
- Add architecture, duplicate, copy, and git-hygiene gates ([67be5e5](https://github.com/schiste/toolhub-evolved/commit/67be5e55b72f394dc208c61293582f2de7e6e901))
- Add strict mutation and contract quality gates ([07a40ae](https://github.com/schiste/toolhub-evolved/commit/07a40ae607cdb539b115c6116e49b04ac42c687c))
- Deduplicate language picker action styles ([f30b779](https://github.com/schiste/toolhub-evolved/commit/f30b779da067033b509b66b4cb3e41ac31d9f6de))
- Add header language picker (English-only prototype) ([e81e82d](https://github.com/schiste/toolhub-evolved/commit/e81e82d56fb0aeaf25305fdb9ad1b9d22030470d))
- Fix runtime accessibility gates ([336d191](https://github.com/schiste/toolhub-evolved/commit/336d19164d320f34e73c46789c43a7db466e7c05))
- Clean CSS design system gates ([7fef629](https://github.com/schiste/toolhub-evolved/commit/7fef629c846a634901da206be6a47614fbd34aef))
- Clean JavaScript quality issues ([edb6fa8](https://github.com/schiste/toolhub-evolved/commit/edb6fa8c1485f17cb065038d6401ed3a317d1505))
- Clean backend and docs quality issues ([3183eee](https://github.com/schiste/toolhub-evolved/commit/3183eeec8bb0d31351653de116afd47c9f8fee9f))
- Add strict quality gate ([475e112](https://github.com/schiste/toolhub-evolved/commit/475e1121194385be2f75be2d55499af42e89db77))
- Theme toggle: drop System option (it is just the default picker) ([379ab33](https://github.com/schiste/toolhub-evolved/commit/379ab33fb063fe9ff66b3db554f983c78cd800d6))
- Expose system theme choice ([3607c1c](https://github.com/schiste/toolhub-evolved/commit/3607c1ca9edf5be01a58ece35c18552a005fb46b))
- Polish navigation and coarse pointer motion ([f9fb3fa](https://github.com/schiste/toolhub-evolved/commit/f9fb3fa6a6086259827c56242b2fef46d6db9df5))
- Clarify experimental form help text ([3b43643](https://github.com/schiste/toolhub-evolved/commit/3b436433b4de82682d3b3d27b66d4bef037ecbcb))
- Stabilize recent changes filters ([fc1a2dd](https://github.com/schiste/toolhub-evolved/commit/fc1a2dd6419f77ff46bdee47164f3c085b27893a))
- Expand frontend API documentation ([2969943](https://github.com/schiste/toolhub-evolved/commit/2969943307dfc6d663ebc1b12efeb4681492e53b))
- Harden blank-target link rels ([1814de0](https://github.com/schiste/toolhub-evolved/commit/1814de0555a2945924fe92a224dfb057825433c7))
- Use denser default search results ([47d3c19](https://github.com/schiste/toolhub-evolved/commit/47d3c194c7f0f3344c5de5b87e9c5e4937c46607))
- Replace review signals with thanks ([0c436f6](https://github.com/schiste/toolhub-evolved/commit/0c436f653ddff5afca01fb1f24088616c5989767))
- Mark complete tool listings discreetly ([f3137a4](https://github.com/schiste/toolhub-evolved/commit/f3137a449cdb0916d816694a076f52c6cc124277))
- Use Toolhub author search for by pages ([893c43d](https://github.com/schiste/toolhub-evolved/commit/893c43dbc5764c18f163b53559f0f656866bfcfd))

## 2026-06-24

### Features

- use clean history URLs ([09a6664](https://github.com/schiste/toolhub-evolved/commit/09a666446f27cda35a8d406b529a442bf2e48173))
- add theme controls and responsive navigation ([ca541cd](https://github.com/schiste/toolhub-evolved/commit/ca541cdccc41a9f675ceecf16727af9d54f34afe))
- add accessible form guidance ([0e73c99](https://github.com/schiste/toolhub-evolved/commit/0e73c99fbed3ee9d7d4e7eabe6a0a74ce3a84afc))
- add search result page-size controls ([386d6a3](https://github.com/schiste/toolhub-evolved/commit/386d6a3065c490e49f32c196b4f97d8ab91b7b90))

### Fixes

- update demo sign-in identity ([56eaf1d](https://github.com/schiste/toolhub-evolved/commit/56eaf1d7c82a18dd192cf332858c7ba4fdaf3994))

### Documentation

- update mock identity plan text ([b0eb51b](https://github.com/schiste/toolhub-evolved/commit/b0eb51b5bda2aabd86f0cde4a8bbfacfc807e729))
- document API schema access ([6a84943](https://github.com/schiste/toolhub-evolved/commit/6a84943fb1101115ff82413199a1954177d4d15b))

### Refactoring

- share live data helper utilities ([6d57f67](https://github.com/schiste/toolhub-evolved/commit/6d57f67a9e97b48e3c0d40f6b69c94a9c690179f))

### Maintenance

- add deploy readiness checks ([dbde8c1](https://github.com/schiste/toolhub-evolved/commit/dbde8c1080b422d238cfe3388f7a0b8640053efb))
- mark outbound links nofollow ([8db699b](https://github.com/schiste/toolhub-evolved/commit/8db699b66b86fd6f91cbb24537eb16464965fffb))
- ignore local Chau7 workspace ([5608aa4](https://github.com/schiste/toolhub-evolved/commit/5608aa4cea0da3668f6e969bea715e6af407fcd9))

### Other

- Update intent builder styleguide examples ([f45624e](https://github.com/schiste/toolhub-evolved/commit/f45624e317d5c132a7bbca1b5d911b7a2a920cd1))
- Style homepage intent controls ([5f8395f](https://github.com/schiste/toolhub-evolved/commit/5f8395f25561ae5065b632abd8d49cc1fa7fa839))
- Add live homepage intent filtering ([9eac2ce](https://github.com/schiste/toolhub-evolved/commit/9eac2ce1c4936b36654595ce4706273df099ec23))
- Batch 3: markdown descriptions, duplicate hints, complete-sort, status filters ([bfe7936](https://github.com/schiste/toolhub-evolved/commit/bfe79367c2587bf2e2972300d37bcf22f89e04b8))
- Batch 2: frontend fixes for 7 open issues (clean-path router) ([180fafa](https://github.com/schiste/toolhub-evolved/commit/180fafa7cbda6fca1b37bc4c6d6209b693ab8ae9))
- Add similarity graph: global tool map + per-tool ego-graph ([5a56448](https://github.com/schiste/toolhub-evolved/commit/5a564480b8da1355fb32fbc7d5f535e30860323d))
- Fix submit link + add Wikidata ID, author links/pages, screenshot polish ([8d6e930](https://github.com/schiste/toolhub-evolved/commit/8d6e9302b62ebf12bad47f352252c87ee57a6bfc))
- Unify control + avatar heights into one vertical scale ([cdafecf](https://github.com/schiste/toolhub-evolved/commit/cdafecf0732f81a75c648eb2649325cd34f8fe23))
- Complete design-system cleanup: tokenize CSS + catalog every element ([172e370](https://github.com/schiste/toolhub-evolved/commit/172e370bc4612de6bfc338a119d0dbd24ccf6f5e))
- Harmonize design-system buttons/controls + add tool-similarity "Related tools" ([a389a50](https://github.com/schiste/toolhub-evolved/commit/a389a50e93948475b38c1162e3c9f74b1fce5bb6))

## 2026-06-23

### Documentation

- deploy note reflects FontCDN (no Google Fonts) ([54f3863](https://github.com/schiste/toolhub-evolved/commit/54f3863483c47fd1e30a745fab192281717310ce))

### Other

- Add honest trust layer from real Toolhub data ([1bca88c](https://github.com/schiste/toolhub-evolved/commit/1bca88c0c2df3d6592b5518258fc248122b92141))
- Remove the 'Getting started' steps section from home ([86298ff](https://github.com/schiste/toolhub-evolved/commit/86298ffcd81950b8eebc349e8ce9fac8d67ba425))
- Hero: in-hero "explore" control with a browse-axis toggle ([9462070](https://github.com/schiste/toolhub-evolved/commit/9462070e922f06ae29feead3533856b8777a311e))
- Replace emoji with the Wikimedia Codex icon set ([13ce1e2](https://github.com/schiste/toolhub-evolved/commit/13ce1e2684cf966ed6d8e983b230ef1913a68657))
- Sidebar: drop the column separator and panel boxes; underline panel titles ([7ab7664](https://github.com/schiste/toolhub-evolved/commit/7ab7664e2b608377bbc85b170d05284489c5e668))
- Squared design: remove all rounded corners; corner-bracket tool cards ([327904e](https://github.com/schiste/toolhub-evolved/commit/327904e4dd40280c26bb03617378caa084e4129c))
- De-slop: native system fonts, flat card hierarchy, specific copy ([354b7c5](https://github.com/schiste/toolhub-evolved/commit/354b7c55cc10cb72986470501f7e44542e631d43))
- Fix Radii/Shadows column alignment on the design-system page ([1d18614](https://github.com/schiste/toolhub-evolved/commit/1d18614ed1bc236ab7b6235de105a1cdb72c70dd))
- Split CSS into Atomic-Design layer files; tokenize values; refine visuals ([ba6ed7f](https://github.com/schiste/toolhub-evolved/commit/ba6ed7fae3e54a4b904ed22e377331eafbfab079))
- Reorganize SPA JS into Atomic-Design layers + add styleguide view ([d4a9878](https://github.com/schiste/toolhub-evolved/commit/d4a98784b596bc480281aa6eca76f7de4142c826))
- Smooth navigation: delay the loading spinner + cache API reads ([e9e24f6](https://github.com/schiste/toolhub-evolved/commit/e9e24f6d5a79302fce746d33729281bf0b03fac0))
- Remove 34 unreferenced doc screenshots ([d53a4f9](https://github.com/schiste/toolhub-evolved/commit/d53a4f989c36b8517fd7e761deee947d7cfee56f))
- Modularize SPA into ES modules; fix 4 bugs; remove dead code/CSS/tokens; drop Google Fonts ([a3c69e7](https://github.com/schiste/toolhub-evolved/commit/a3c69e7dd298b132ccd59f33bd4518cd38b99579))

## 2026-06-22

### Other

- Differentiate home shortcuts: personas=audiences, needs=tasks (real facets) ([0c8348a](https://github.com/schiste/toolhub-evolved/commit/0c8348aa72b0282600cb22b8d5440178dd8cca67))
- Drop redundant Experimental badges on the #/experiments page ([a7be110](https://github.com/schiste/toolhub-evolved/commit/a7be110c188f950a0e7bac5c8e0430a08583ce97))
- Add an Experimental features index page, linked from the banner ([2f64ccc](https://github.com/schiste/toolhub-evolved/commit/2f64ccc0cfc229224c6b2a8cbc08fb57b4a8f934))
- a11y polish: card-grid list semantics + crawler table caption/scope ([e687f36](https://github.com/schiste/toolhub-evolved/commit/e687f362db8d881a38c7069ced402cc6d6032513))
- Phase 6: unify synthetic signals as per-tool overlays ([752187e](https://github.com/schiste/toolhub-evolved/commit/752187ee40391e6c2b71b5a1f2bf2215b953ddfa))
- Phase 5: add/remove-tools crawler simulation ([09d09e9](https://github.com/schiste/toolhub-evolved/commit/09d09e9f6490f6a59b222ccf11e4e3809af72567))
- Phase 4: tool submit/edit + annotations + local revision/audit ([9dd4951](https://github.com/schiste/toolhub-evolved/commit/9dd4951e75567b17c50bd2b3fdf59251ea424fbf))
- Phase 3: Lists CRUD (demo overlay) ([b5061bf](https://github.com/schiste/toolhub-evolved/commit/b5061bf1c1760c14558b06247be63335a0770f06))
- Phase 2 (2/2): demoStore overlay, mock identity, favorites ([28ec0bb](https://github.com/schiste/toolhub-evolved/commit/28ec0bb1fecd18e17bec88cff54d2ba356548b44))
- Phase 2 (1/2): default-off toggle, mockup banner, Rules of Engagement ([a5aee4e](https://github.com/schiste/toolhub-evolved/commit/a5aee4e67e40cbaeceaeb96f02c586bc4a9b61a6))
- Resolve plan decisions; add mockup banner + Rules of Engagement ([2cba2f8](https://github.com/schiste/toolhub-evolved/commit/2cba2f8351316b3d1a4986b49a18b3e0a9553b43))
- Reframe Lane B as live data overloaded with feature fixtures ([a66d0b3](https://github.com/schiste/toolhub-evolved/commit/a66d0b31bcf6acccb42a3a62dea23386b3925b8b))
- Add the unified plan doc and README roadmap ([46f749a](https://github.com/schiste/toolhub-evolved/commit/46f749a2af9a7afc6a17363697e63a10dd409ff9))
- Merge the three reviews into one comprehensive plan ([fe8fe59](https://github.com/schiste/toolhub-evolved/commit/fe8fe5978cacf99b28726e0556711be89d851fcc))
- Ignore python cache and local venv ([aa51fe5](https://github.com/schiste/toolhub-evolved/commit/aa51fe520906edc8e3a7410620799bf3978ed1fb))
- Merge agent/i18n-a11y: i18n + a11y audit and fixes ([41824b5](https://github.com/schiste/toolhub-evolved/commit/41824b588db71f7e2daa87f2ecff33fd528ffbe3))
- Merge agent/demo-plan: standalone-demo architecture plan ([160a704](https://github.com/schiste/toolhub-evolved/commit/160a704059f9419b74b5b3017fc949b554a2957a))
- Merge agent/fix-features: fix 7 live-data feature defects ([dd8813c](https://github.com/schiste/toolhub-evolved/commit/dd8813cfb3c6e7307221b991adefcb5104e314b3))
- Fix Toolhub SPA live data regressions ([777f0c2](https://github.com/schiste/toolhub-evolved/commit/777f0c20f54e9cc035e16366e978b16c1a27de7e))
- Document i18n and accessibility audit ([1db048d](https://github.com/schiste/toolhub-evolved/commit/1db048d223d594c241a057b97f9bd1c7fb1e03a8))
- Improve i18n and accessibility primitives ([c772e73](https://github.com/schiste/toolhub-evolved/commit/c772e73dad29bfbcff46c4298851dd5cfa3c23aa))
- Plan standalone Toolhub demo architecture ([8cb3854](https://github.com/schiste/toolhub-evolved/commit/8cb3854794e24c59d9af409ae54c3c8e4d3e5edc))

## 2026-06-21

### Other

- Escape API fields in HTML sinks (XSS hardening) ([e25eeb0](https://github.com/schiste/toolhub-evolved/commit/e25eeb08d17b9c49b9158235f0f70216cfa37c13))
- Docs: describe the live-proxy architecture ([8615e2d](https://github.com/schiste/toolhub-evolved/commit/8615e2d99d31dcbda8cad1de675b58aba66529f5))
- Drop the bundled snapshot; the SPA is live-only ([81ae769](https://github.com/schiste/toolhub-evolved/commit/81ae76988e3e7c2410402a410ea82f771645d923))
- Style live feed/runs views (feed**static, feed**sub, runs table) ([2e844d1](https://github.com/schiste/toolhub-evolved/commit/2e844d153cd1a75d6c65d6f6297bd50206000ec0))
- Wire all read views to the live Toolhub API ([fa4f5da](https://github.com/schiste/toolhub-evolved/commit/fa4f5dae240c0639d34058de8e598addc03e1afd))
- Switch Toolforge to the Python webservice (live API proxy) ([76336de](https://github.com/schiste/toolhub-evolved/commit/76336de6a58040f2d21daa2b489a8594e1bfa7cf))
- Add read-only API proxy (Flask) for live Toolhub data ([946b52f](https://github.com/schiste/toolhub-evolved/commit/946b52f1189768d232c87831c79e1885d3acdae3))

## 2026-06-11

### Other

- Expbar uses the page background, not the header ([367fcfe](https://github.com/schiste/toolhub-evolved/commit/367fcfebe70975aa05f7a3ef0c95bfa2e16bdb03))
- Make the prospective-features toggle very discreet ([84464b0](https://github.com/schiste/toolhub-evolved/commit/84464b0d614d5c0e6e83db35d86b019538388432))
- Move experimental toggle to its own strip below the header ([6c4ba22](https://github.com/schiste/toolhub-evolved/commit/6c4ba22a0a6ef728621e9332cb2c1d5bc2be1bad))
- Make the header profile avatar round ([6806230](https://github.com/schiste/toolhub-evolved/commit/68062302c71c8f78c0f900d6897b3c1beacd9468))
- Harmonise button sizing on the golden scale ([fcddd78](https://github.com/schiste/toolhub-evolved/commit/fcddd78202064f4f68e45088f47dfb542e7d94d9))
- Add logged-in user fixture + account dropdown in the header ([4c73208](https://github.com/schiste/toolhub-evolved/commit/4c73208e64303e2945f2232aab7aed96ba2bffbd))

## 2026-06-10

### Other

- Tighten gap between persona filters and the first section ([c5bc373](https://github.com/schiste/toolhub-evolved/commit/c5bc3737aa199b64012d29bc97f47922c5da0317))
- Use the real Toolhub logo ([98add10](https://github.com/schiste/toolhub-evolved/commit/98add1064da89a81f6de03527bf29f213869b755))
- Enforce a golden-ratio (φ) design system across the UI ([8169b81](https://github.com/schiste/toolhub-evolved/commit/8169b81a5b05ae55cf18aef003ba33a47cb8e2bd))
- Cleaner tool cards: real metadata instead of an assumed status ([067aaf7](https://github.com/schiste/toolhub-evolved/commit/067aaf7c5714faa6749ccbeda5ca5c603ab2866b))
- Tool cards open the quick-view by default ([0ea59f2](https://github.com/schiste/toolhub-evolved/commit/0ea59f237788ec06d8dfad0693bbb7005aa8231e))
- Improve tool detail: add quick-view peek modal + redesign full page ([d407837](https://github.com/schiste/toolhub-evolved/commit/d407837b892b3868bce60eea4a7dcad62286a63f))
- Reach Toolhub parity: add maintenance/admin pages + full footer sitemap ([8ce4707](https://github.com/schiste/toolhub-evolved/commit/8ce47077bbdfe6640eeefc0c68a620b77cf5be89))
- Rename project to Toolhub Evolved; fix Toolforge tool name in deploy docs ([bb050fe](https://github.com/schiste/toolhub-evolved/commit/bb050fee0ca4194a50a625ffa2618cf25c0baf8b))
- Initial commit: Toolforge Evolved — Toolhub discovery demonstrator ([650cb54](https://github.com/schiste/toolhub-evolved/commit/650cb5408dc01e3b62583231bccefb41859f4e76))
