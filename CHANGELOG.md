# Changelog

All notable Toolhub Evolved changes, grouped from the repository's Git history.
This file is generated with `npm run changelog:generate`; do not edit it by hand.

## 2026-08-03

### Features

- add deploy changelog announcements ([8a5f07b](https://github.com/schiste/toolhub-evolved/commit/8a5f07b4b229167c816784252b464aba83d068d4))

### Performance

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
