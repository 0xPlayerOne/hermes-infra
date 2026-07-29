# Changelog

## 0.1.0 (2026-07-29)


### Features

* dual-index search across code + second-brain ([f07ba9f](https://github.com/0xPlayerOne/hermes-infra/commit/f07ba9fe7f8c8b8797335a477293a81dad33e1ac))
* enhance agents.md file generation with /init ([3e11140](https://github.com/0xPlayerOne/hermes-infra/commit/3e1114074ddec3623f903e6238cb2fcdfff660c2))
* reduce code-foundry consumer footprint ([9839b3d](https://github.com/0xPlayerOne/hermes-infra/commit/9839b3d781d71bdfef2d3371e73c70660cbf4ea4))
* second-brain prose indexer with markdown-aware chunking ([3400f11](https://github.com/0xPlayerOne/hermes-infra/commit/3400f11feed37e325b51d617d3f48b2ab783748f))


### Bug Fixes

* **cache:** detect restored Bun installs ([11bb2a8](https://github.com/0xPlayerOne/hermes-infra/commit/11bb2a888373cf436cfbd400a263c9267ec10073))
* **cache:** require exact Bun dependency matches ([c75a9cf](https://github.com/0xPlayerOne/hermes-infra/commit/c75a9cf1f253a53c910c397642a241651fa8b9d9))
* **ci:** activate build cache for build task ([6bcc348](https://github.com/0xPlayerOne/hermes-infra/commit/6bcc348e8ff2809ebe1fe2f9fd7c3d5d3e010555))
* **ci:** always activate detected build cache ([d562059](https://github.com/0xPlayerOne/hermes-infra/commit/d562059075fccde11f092f9e425cdb26a32e1a70))
* **codeql:** restore valid matrix workflow ([5fb65fa](https://github.com/0xPlayerOne/hermes-infra/commit/5fb65fafdf732f402e7d2d43e0015ec11d712d37))
* detect native Bun coverage runners ([40714dd](https://github.com/0xPlayerOne/hermes-infra/commit/40714ddcb67801b8235ea55ba03a32417a5b8052))
* enforce function and line coverage ([a8aec7a](https://github.com/0xPlayerOne/hermes-infra/commit/a8aec7a33bac814b15e0a5bba60913483a3e3e44))
* Hindsight API endpoints + sync daemon lifecycle + infra health checks ([cde25a7](https://github.com/0xPlayerOne/hermes-infra/commit/cde25a7b67fa20d2dfecf29f87752a891d530f76))
* ignore shared helper files in language detection ([5fc7c5f](https://github.com/0xPlayerOne/hermes-infra/commit/5fc7c5fd0e87251242a9cbebcafd6d32ea9b398a))
* install Rust CI components ([385dc96](https://github.com/0xPlayerOne/hermes-infra/commit/385dc96d862d38bf7d5a56079cf0195d01e8a08e))
* isolate Python coverage environment ([a76cf9c](https://github.com/0xPlayerOne/hermes-infra/commit/a76cf9c5775e889f5a690c72a7d6b18b044a5c76))
* isolate Python coverage from mise environment ([4f552cd](https://github.com/0xPlayerOne/hermes-infra/commit/4f552cdd5643b69e52493c6021f3a2ba77aed124))
* isolate Python coverage sysconfig workaround ([837f945](https://github.com/0xPlayerOne/hermes-infra/commit/837f945b52916e206f1362ebd90d5dbde77cc7ff))
* pass explicit Python coverage sources ([3e2c216](https://github.com/0xPlayerOne/hermes-infra/commit/3e2c2164c3f71e2f0f2c1ff716a444f13c26df26))
* remove obsolete consumer helper ([866b812](https://github.com/0xPlayerOne/hermes-infra/commit/866b812b4d79e5173dc8194db6b6d6b8ffef28bf))
* repair Rust unit checks and Python test tooling ([cd628b2](https://github.com/0xPlayerOne/hermes-infra/commit/cd628b20d2b790ddcdb2f8c847e5e7cb9cd3c094))
* restore 2-space indent on release body bullet ([e12fd78](https://github.com/0xPlayerOne/hermes-infra/commit/e12fd78d6285b1d09d68fd2f768015bc6aae238c))
* revert chromadb from 1.5.9 to 0.5.23 (critical CVE-2026-45829) ([efae362](https://github.com/0xPlayerOne/hermes-infra/commit/efae36240f41bd2baf48a68e5a4a724fea09fc79))
* **security:** audit conflicting Python manifests independently ([53fa727](https://github.com/0xPlayerOne/hermes-infra/commit/53fa7277681e42746103b983c3f215cf6d38cfa2))
* **security:** detect all Python requirement manifests ([8ec1207](https://github.com/0xPlayerOne/hermes-infra/commit/8ec12073c57fc97a27c8edcc59c274603a2189e7))
* **security:** name skipped Python audits clearly ([90c5425](https://github.com/0xPlayerOne/hermes-infra/commit/90c5425471dc56e5a26df397cbc775d073d13a51))
* **security:** provide stable Python audit gate ([dfb7b0e](https://github.com/0xPlayerOne/hermes-infra/commit/dfb7b0e69d8d6433c4f579dc7ba2cbe94e9262b4))
* **security:** retain pinned Rust audit toolchain ([6881144](https://github.com/0xPlayerOne/hermes-infra/commit/688114495eaa62902b722702d2c2080804abc8cf))
* **security:** skip unchanged ecosystem audits ([1e2773e](https://github.com/0xPlayerOne/hermes-infra/commit/1e2773e76313dcb4547c1beab1f3f77f387dbcda))
* **setup:** correct action yaml indentation ([1ab106b](https://github.com/0xPlayerOne/hermes-infra/commit/1ab106b081e8584c5f84848a5926324605fdd4e6))
* **setup:** pin uv action for Python workflows ([f279ffe](https://github.com/0xPlayerOne/hermes-infra/commit/f279ffe178fc7ed88f36d6e4949b02ac71c86374))
* stabilize coverage and dependency audits ([666b245](https://github.com/0xPlayerOne/hermes-infra/commit/666b2454a15f917019a9871c1ab6a06ed9d984ba))
* support macOS bash in CI helpers ([094f810](https://github.com/0xPlayerOne/hermes-infra/commit/094f810a01898f893f4f10d0a3563e4685f7d2ab))
* support native and jest coverage reports ([d2d996f](https://github.com/0xPlayerOne/hermes-infra/commit/d2d996fd1f8d6af8b8de66cb7de9fa51c9365122))
* update synthesize.py Hindsight URL to v1 endpoint ([013b2f4](https://github.com/0xPlayerOne/hermes-infra/commit/013b2f4dd8bb869de028daca8c6336a4aa452fb7))


### Performance Improvements

* **cache:** allow measured Bun package overrides ([662fedf](https://github.com/0xPlayerOne/hermes-infra/commit/662fedf35daa8c3d9de27dddbf4fd7f0ad077a01))
* **cache:** avoid duplicate parallel saves ([b5e4ea8](https://github.com/0xPlayerOne/hermes-infra/commit/b5e4ea8c55408f705bc2af922053c26e1c760846))
* **cache:** bound Bun dependency archives ([12dfc95](https://github.com/0xPlayerOne/hermes-infra/commit/12dfc95a7665275671077dc8f74bf84f0968b56a))
* **cache:** honor restore-only workflow jobs ([c4c92fb](https://github.com/0xPlayerOne/hermes-infra/commit/c4c92fb716d6600a32ab2db8c6306e6d69795f91))
* **ci:** adapt package cache to lockfile size ([c2a34f2](https://github.com/0xPlayerOne/hermes-infra/commit/c2a34f21671a2329263fcc2ffaa080071d72f8f4))
* **ci:** apply repo-foundry workflow optimizations ([8f53de7](https://github.com/0xPlayerOne/hermes-infra/commit/8f53de7ce30d6ab575d0d3ea7e4d8ae364f122ef))
* **ci:** avoid formatter probe overhead ([cf1b94b](https://github.com/0xPlayerOne/hermes-infra/commit/cf1b94b868b33846d103bae02d66811639986623))
* **ci:** avoid unprofitable js build caches ([9e65a0d](https://github.com/0xPlayerOne/hermes-infra/commit/9e65a0d8af1981273ae67913cd80a0998d8502ba))
* **ci:** bootstrap direct prettier ([6c308b8](https://github.com/0xPlayerOne/hermes-infra/commit/6c308b8f60442902a1fffc1e1dd88f5fc1238161))
* **ci:** default to preloaded runner ([9125e8c](https://github.com/0xPlayerOne/hermes-infra/commit/9125e8c45746a075c09e1990882aaa1d4bfa5982))
* **ci:** default Unit tests to slim runner ([b3bc544](https://github.com/0xPlayerOne/hermes-infra/commit/b3bc54496fb692d085d7c51bb2849f971480dd90))
* **ci:** enable framework build caches ([8ba9952](https://github.com/0xPlayerOne/hermes-infra/commit/8ba9952b47ac00f93c99bb391bc95b60109ed019))
* **ci:** scope turbo cache to active task ([e319f4f](https://github.com/0xPlayerOne/hermes-infra/commit/e319f4f79c3b3ad318bcf0f15242e0ef02d38be1))
* **ci:** skip Bun cache archives for workspaces ([b42d809](https://github.com/0xPlayerOne/hermes-infra/commit/b42d809a73c6dcf9ef491720b70db0e022d9f000))
* **ci:** skip installs on turbo cache hits ([b7be09a](https://github.com/0xPlayerOne/hermes-infra/commit/b7be09aea0223ab208cfeec222fffb5f20954900))
* **ci:** use lean runner for format and lint ([bc8aa7e](https://github.com/0xPlayerOne/hermes-infra/commit/bc8aa7e26a3a552e0d9665889a545c2b42ed1021))
* **codeql:** skip unchanged analyzers before runners ([bc0fcbe](https://github.com/0xPlayerOne/hermes-infra/commit/bc0fcbed0ba50e83ce936bc0f90102489d707dd4))
* **experiment:** cache Hermes test environment ([86edb1b](https://github.com/0xPlayerOne/hermes-infra/commit/86edb1b080566aac00d521f781fad320d69fb9f0))
* **python:** avoid duplicate uv setup ([3f9de97](https://github.com/0xPlayerOne/hermes-infra/commit/3f9de974670a42cb68921dbe06bb9d447f049a38))
* **security:** audit all Python requirements once ([42bc28e](https://github.com/0xPlayerOne/hermes-infra/commit/42bc28ee0e364fe854904ec1da542b6ad37ca32e))
* **security:** bootstrap uv for Python audits ([ee1567b](https://github.com/0xPlayerOne/hermes-infra/commit/ee1567b46377c4b468c5258102693f67e39b0a6a))
* **security:** cache pinned Python auditor ([d2b98a5](https://github.com/0xPlayerOne/hermes-infra/commit/d2b98a58dc446300b39eb23e8ae1bbac36d34be6))
* **security:** cache Rust toolchains ([a759d32](https://github.com/0xPlayerOne/hermes-infra/commit/a759d32be87799b003b87263e9451ffa18bbe020))
* **security:** fan out Python dependency audits ([c44d3cb](https://github.com/0xPlayerOne/hermes-infra/commit/c44d3cbc3a62a8dac5b9d104428f846fa4c1dd0f))
* **security:** gate audits from shared profile ([9cc0c5a](https://github.com/0xPlayerOne/hermes-infra/commit/9cc0c5a97115df60bd9aa20182b97068cd4096f8))
* **security:** guard empty Python audit matrix ([20f404a](https://github.com/0xPlayerOne/hermes-infra/commit/20f404a024182a2dcc11a4dbfd1e3f8cc55cbea6))
* **security:** keep active audits parallel ([a0ec3c9](https://github.com/0xPlayerOne/hermes-infra/commit/a0ec3c9c94b50706d3e784a34a8ed2f659a2a84f))
* **security:** remove redundant Rust tool cache ([dbcae14](https://github.com/0xPlayerOne/hermes-infra/commit/dbcae14d46878062b9caeb5cdf5c9d92a9efc642))
* **security:** skip unused Python package cache ([c279aa4](https://github.com/0xPlayerOne/hermes-infra/commit/c279aa44ca88f0d5754aa0b01c140e5fbde9a0c8))
* **security:** start audits concurrently ([25878b8](https://github.com/0xPlayerOne/hermes-infra/commit/25878b890e6887b88c996145552182da9451e77e))
* **security:** use preinstalled Rust toolchain ([107cf00](https://github.com/0xPlayerOne/hermes-infra/commit/107cf005bfcfa6971a528c118f9ed214e3034a36))
* **security:** use runner Rust toolchain for audits ([c8337a5](https://github.com/0xPlayerOne/hermes-infra/commit/c8337a548acb0aa74b05044c4adb629caca0e583))
* **setup:** skip duplicate build cache with remote turbo ([1075174](https://github.com/0xPlayerOne/hermes-infra/commit/10751741be9a66b38e70709ddcb1a2954a51f7be))
* **setup:** skip lint cache outside lint jobs ([bb81bca](https://github.com/0xPlayerOne/hermes-infra/commit/bb81bca310d823ddca0b2cafa4f774848f961b7f))
* **template:** skip unused formatter caches ([f9491b8](https://github.com/0xPlayerOne/hermes-infra/commit/f9491b8392f1a21c458bc46fb096d8b8750ae995))
* **template:** speed up CodeQL detection ([7370f92](https://github.com/0xPlayerOne/hermes-infra/commit/7370f928a9592654c9bafcae0d52ab70e9778152))
* **template:** use current Turbo remote cache mode ([838498d](https://github.com/0xPlayerOne/hermes-infra/commit/838498d114f002db3700c4224a0439d7913c8f78))
* **test:** cache Rust integration builds ([543936b](https://github.com/0xPlayerOne/hermes-infra/commit/543936b1707ef0afe08f9f53308663d73feed56b))
* **test:** use slim runner for unit checks ([e21be8c](https://github.com/0xPlayerOne/hermes-infra/commit/e21be8cf4242b636f33642611465229f1639dd4b))
* **workflows:** bound automation jobs ([2533b15](https://github.com/0xPlayerOne/hermes-infra/commit/2533b15c354cfd28589fd1c6cc26b4e2990b477e))
* **workflows:** bound hosted job time ([b4f6cd5](https://github.com/0xPlayerOne/hermes-infra/commit/b4f6cd5cae96bd9c68c38f311a0fab556e5227b6))
* **workflows:** cancel stale branch runs ([f724cd4](https://github.com/0xPlayerOne/hermes-infra/commit/f724cd480d9f3d6c88117070a0b0c845e109ca72))
* **workflows:** deduplicate same-commit runs ([bd5d638](https://github.com/0xPlayerOne/hermes-infra/commit/bd5d6385d4c3d2e29bddc62fa2545b206ccdb616))


### Reverts

* **experiment:** avoid Python environment archive ([b6c3fdf](https://github.com/0xPlayerOne/hermes-infra/commit/b6c3fdf252818df02e643600a7eac76194f88ac8))

## Changelog

All notable changes to this project are documented here.
