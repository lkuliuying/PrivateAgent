# 签名、信任与密钥治理（第五阶段 M3）

> 对应 `docs/phase5-plan.md` M3 与 `docs/phase5-requirements.md` 5.5。
> 私人助手有两层独立的"签名"，职责不同，必须分清：

| 层 | 作用 | 当前状态 | 失败后果 |
|---|---|---|---|
| **Tauri updater 签名**（`.sig`） | 校验自动更新下载的安装包完整性与来源 | 已接入（私钥本地持有，公钥写入 `tauri.conf.json`） | updater 拒绝更新；用户无法应用内升级 |
| **Windows 代码签名**（Authenticode） | 消除 SmartScreen 警告，显示发布者身份 | 未接入（无证书） | 首次运行 SmartScreen 拦截，需手动"仍要运行" |

这两层互不替代：updater 签名防"更新被篡改"，代码签名防"安装包被 Windows 拦截"。

---

## 1. Tauri updater 签名

### 1.1 密钥对

- **私钥**：`%USERPROFILE%\.tauri\personal-assistant.key`（仅本地持有，**严禁入库**）。
- **私钥密码**：`%USERPROFILE%\.tauri\personal-assistant.key.pwd`（构建时非交互读取，避免 `tauri build` 卡在密码提示）。
- **公钥**：`%USERPROFILE%\.tauri\personal-assistant.key.pub`，其内容已写入 `apps/desktop/src-tauri/tauri.conf.json` 的 `plugins.updater.pubkey`。

> 已验证（2026-07-08）：`tauri.conf.json` 的 `pubkey` 与本地 `.key.pub` 内容逐字节一致（152 字符），且构建产物的 `.sig` 由该私钥签出，签名链端到端一致。

### 1.2 生成 / 轮换密钥

```bash
# 生成新密钥对（在 apps/desktop 下执行，借助项目的 @tauri-apps/cli）
cd apps/desktop
npx tauri signer generate -w "%USERPROFILE%\.tauri\personal-assistant.key"
# 会提示设置密码；把密码写入 .key.pwd 供自动化构建读取
```

轮换密钥后：

1. 用新公钥覆盖 `tauri.conf.json` 的 `plugins.updater.pubkey`。
2. 旧版本应用内嵌的是旧公钥，**无法验证用新私钥签的更新**。轮换策略：
   - 在最后一个"用旧公钥"的版本里，先发布一个"切换公钥"的过渡版本仍用旧私钥签；
   - 或要求用户手动下载带新公钥的版本一次，之后再恢复自动更新。
3. 把轮换事件记入发布清单的 `known_issues`。

### 1.3 构建时签名

`scripts/build-release.bat` 自动处理：

- 检测 `%USERPROFILE%\.tauri\personal-assistant.key` 存在时，读取私钥与密码到 `TAURI_SIGNING_PRIVATE_KEY` / `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`。
- `tauri build` 因 `createUpdaterArtifacts: true` 用该私钥对 NSIS 安装包签出 `*.exe.sig`。
- 无私钥时跳过 `.sig`，并在日志提示"updater will reject updates"。

### 1.4 验证 `.sig` 与 `latest.json`

发布前自检（确保 `latest.json` 的 `signature` 与磁盘 `.sig` 一致）：

```bash
# 生成 latest.json（signature 字段直接取自 .sig）
uv run python scripts/generate-latest-json.py --out dist/latest.json

# 校验：latest.json 的 signature 应等于 .sig 文件内容
python -c "import json,pathlib; \
  j=json.load(open('dist/latest.json',encoding='utf-8'))['platforms']['windows-x86_64']['signature']; \
  s=pathlib.Path('apps/desktop/src-tauri/target/release/bundle/nsis').glob('*-setup.exe.sig'); \
  print('sig match:', j==next(s).read_text(encoding='utf-8').strip())"
```

应用内"检查更新"在下载安装包后会用 `tauri.conf.json` 的公钥校验 `.sig`；签名不匹配时 `UpdateChecker.vue` 显示"更新签名验证失败，已拒绝更新"（见 `apps/desktop/src/components/UpdateChecker.vue` 的错误分类）。

### 1.5 私钥保存策略

| 场景 | 私钥位置 | 适用 |
|---|---|---|
| 个人 / 单机发布 | 本地 `%USERPROFILE%\.tauri\personal-assistant.key` | 当前默认；本项目主力路径 |
| CI 发布（GitHub Actions） | Repository secret `TAURI_SIGNING_PRIVATE_KEY` + `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | 多人协作或自动化发布时 |

`.gitignore` 已覆盖 `.tauri/`、`*.key`、`*.key.pwd`、`*.pem`、`*.p12`、`*.pfx`、`*.cert`。已确认 `git ls-files` 不含任何私钥或证书。

---

## 2. Windows 代码签名（Authenticode，未接入）

当前安装包**未代码签名**，首次运行会触发 Windows SmartScreen："Windows 已保护你的电脑"。用户需点"更多信息 -> 仍要运行"。这是个人/开源项目可接受的过渡状态，但应在发布说明中透明提示。

### 2.1 证书选型

| 类型 | 成本（年） | SmartScreen | 特点 |
|---|---|---|---|
| 自签名 | 0 | 仍拦截 | 仅消除"未知发布者"字样，不解决 SmartScreen |
| OV（组织验证） | ~$200–400 | 需积累信誉后才不拦截 | 个人项目门槛较高（需组织身份） |
| EV（扩展验证） | ~$300–700 | 立即不拦截 | 需硬件 token/USB，最贵但最稳 |

> SmartScreen 信誉：OV 证书签名的应用随下载量积累信誉后，SmartScreen 拦截会逐步消失；EV 证书即时通过。对个人项目，可先用 OV 积累，或接受自签名 + 文档说明。

### 2.2 signtool 接入方式

购买证书后（通常为 `.pfx`/`.p12`），用 Windows SDK 的 `signtool` 签名：

```bash
signtool sign /fd SHA256 /f <cert.pfx> /p <password> /tr http://timestamp.digicert.com /td SHA256 <installer.exe>
signtool verify /pa /v <installer.exe>
```

- `/tr`：RFC 3161 时间戳服务器（DigiCert / Sectigo 等），保证证书过期后签名仍有效。
- `/fd SHA256` / `/td SHA256`：签名与时间戳摘要算法。
- 证书私钥的 `.pfx`/`.p12` **严禁入库**（`.gitignore` 已覆盖）。

### 2.3 签名顺序（关键）

Tauri updater 的 `.sig` 是对**安装包字节**的签名。代码签名（Authenticode）会**修改安装包字节**（追加签名块）。因此顺序必须是：

```
1. tauri build 产出 NSIS 安装包（若配置了 updater 私钥，此时也产出 .sig）
   ── 但此 .sig 是对【未代码签名】安装包的签名 ──
2. signtool 对安装包做 Authenticode 签名（字节改变）
3. 重新用 tauri signer 对【已代码签名】安装包生成 .sig（覆盖第 1 步的 .sig）
4. generate-latest-json.py 用第 3 步的 .sig 生成 latest.json
```

> 即：**先代码签名，后 updater 签名**，且 `latest.json` 的 `signature` 必须取自最终（代码签名后）的 `.sig`。否则应用下载安装包后用公钥校验会失败（字节不匹配）。

第 3 步可用：

```bash
npx tauri signer sign -k "%USERPROFILE%\.tauri\personal-assistant.key" \
  -p "<password>" -f "<installer.exe>"
# 生成 <installer.exe>.sig
```

### 2.4 接入后的发布清单增量

代码签名接入后，`scripts/build-release.bat` 与 `docs/release-checklist.md` 需新增：

- [ ] `signtool sign` 步骤（在 tauri build 之后、`generate-latest-json.py` 之前）。
- [ ] `signtool verify /pa /v` 通过。
- [ ] 重新 `tauri signer sign` 生成最终 `.sig`，再生成 `latest.json`。
- [ ] 发布说明删除"未签名 SmartScreen 风险"提示。

未接入前，`docs/release-checklist.md` 与 `README.md` 保留 SmartScreen 风险提示与绕过方式。

---

## 3. 当前状态小结

- ✅ updater 私钥本地持有，公钥与 `tauri.conf.json` 一致，`.gitignore` 覆盖密钥与证书，仓库不含私钥。
- ✅ 构建自动生成 `.sig`；`generate-latest-json.py` 自动产出与 `.sig` 一致的 `latest.json`。
- ✅ `UpdateChecker.vue` 区分网络/清单/签名/无更新错误。
- ⏳ Windows 代码签名未接入：发布说明需保留 SmartScreen 风险提示；证书采购与 signtool 接入方案已明确（见 §2），待证书到位后执行。
