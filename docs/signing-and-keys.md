# 签名、信任与密钥治理（第五阶段 M3）

> 对应 `docs/archive/phases/phase5-plan.md` M3 与 `docs/archive/phases/phase5-requirements.md` 5.5。
> 私人助手有两层独立的"签名"，职责不同，必须分清：

| 层 | 作用 | 当前状态 | 失败后果 |
|---|---|---|---|
| **Tauri updater 签名**（`.sig`） | 校验自动更新下载的安装包完整性与来源 | 已接入（私钥本地持有，公钥写入 `tauri.conf.json`） | updater 拒绝更新；用户无法应用内升级 |
| **Windows 代码签名**（Authenticode） | 消除 SmartScreen 警告，显示发布者身份 | SignPath 可信构建已入库；等待 OSS 订阅审批与首次实签 | 未获批前仍按 unsigned 策略发布 |

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

## 2. Windows 代码签名（Authenticode）

本地候选安装包当前尚未代码签名。仓库已接入 SignPath Foundation 免费 OSS 签名所需的公开许可证、代码签名政策和 GitHub 托管可信构建；在申请获批、项目变量和密钥配置完成之前，构建仍如实执行 unsigned 透明策略。

### 2.1 证书选型

| 类型 | 成本（年） | SmartScreen | 特点 |
|---|---|---|---|
| SignPath Foundation OSS | 0 | 公开信任证书；仍受 SmartScreen 信誉机制影响 | 推荐；私钥位于 SignPath HSM，要求公开 OSS、可信构建和人工批准 |
| 自签名 | 0 | 仍拦截 | 仅消除"未知发布者"字样，不解决 SmartScreen |
| OV（组织验证） | ~$200–400 | 需积累信誉后才不拦截 | 个人项目门槛较高（需组织身份） |
| EV（扩展验证） | ~$300–700 | 立即不拦截 | 需硬件 token/USB，最贵但最稳 |

> SmartScreen 信誉由 Microsoft 独立判定。Authenticode 有效签名可以显示可信发布者和保持文件完整性，但不能承诺所有设备立即不再提示。

### 2.2 SignPath OSS 可信构建

工作流：`.github/workflows/signpath-release.yml`。

1. GitHub 托管的 `windows-latest` 执行器从发布 tag 构建 NSIS 安装包。
2. `actions/upload-artifact` 先把未签名安装包固化为 GitHub Actions artifact。
3. `signpath/github-action-submit-signing-request@v2` 按 artifact ID 提交签名请求；SignPath 验证工作流来源并等待人工批准。
4. 工作流下载签名结果，用 Windows Authenticode API 验证 `Valid` 状态并记录 provider/证书主题。
5. 对最终签名后的安装包重新生成 Tauri updater `.sig` 和 `latest.json`。
6. 仅在上述步骤全部成功后，将安装包、`.sig`、`latest.json` 与发布证据上传到主仓库 Release。

SignPath 订阅建立后需要配置：

| GitHub 配置 | 类型 | 说明 |
|---|---|---|
| `SIGNPATH_API_TOKEN` | Actions secret | 仅具备对应项目/策略的 submitter 权限 |
| `SIGNPATH_ORGANIZATION_ID` | Actions variable | SignPath 组织 ID |
| `SIGNPATH_PROJECT_SLUG` | Actions variable | 建议值 `PrivateAgent`，以 SignPath 实际生成值为准 |
| `SIGNPATH_SIGNING_POLICY_SLUG` | Actions variable | 建议值 `release-signing`，以 SignPath 实际生成值为准 |
| `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG` | Actions variable | Windows installer artifact configuration 的实际 slug |
| `TAURI_SIGNING_PRIVATE_KEY` | Actions secret | Tauri updater 私钥，与 Authenticode 证书无关 |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Actions secret | updater 私钥密码（如有） |

仓库主页的 [Code signing policy](../CODE_SIGNING_POLICY.md) 定义团队角色、隐私声明、发布控制与事件处置。申请准备和待人工步骤见 [SignPath OSS 申请清单](signpath-application.md)。

### 2.3 本地证书 / signtool 回退方式

购买证书后（通常为 `.pfx`/`.p12`），用 Windows SDK 的 `signtool` 签名：

```bash
signtool sign /fd SHA256 /f <cert.pfx> /p <password> /tr http://timestamp.digicert.com /td SHA256 <installer.exe>
signtool verify /pa /v <installer.exe>
```

- `/tr`：RFC 3161 时间戳服务器（DigiCert / Sectigo 等），保证证书过期后签名仍有效。
- `/fd SHA256` / `/td SHA256`：签名与时间戳摘要算法。
- 证书私钥的 `.pfx`/`.p12` **严禁入库**（`.gitignore` 已覆盖）。

### 2.4 签名顺序（关键）

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

### 2.5 接入后的发布清单增量

代码签名接入后，`scripts/build-release.bat` 与 `docs/release-checklist.md` 需新增：

- [ ] SignPath 返回签名产物，或本地 `signtool sign` 步骤完成（均在 tauri build 之后、`generate-latest-json.py` 之前）。
- [ ] `signtool verify /pa /v` 通过。
- [ ] 重新 `tauri signer sign` 生成最终 `.sig`，再生成 `latest.json`。
- [ ] 发布说明删除"未签名 SmartScreen 风险"提示。

未接入前，`docs/release-checklist.md` 与 `README.md` 保留 SmartScreen 风险提示与绕过方式。

---

## 3. 当前状态小结

- ✅ updater 私钥本地持有，公钥与 `tauri.conf.json` 一致，`.gitignore` 覆盖密钥与证书，仓库不含私钥。
- ✅ 构建自动生成 `.sig`；`generate-latest-json.py` 自动产出与 `.sig` 一致的 `latest.json`（第八阶段 M5 起支持多平台）。
- ✅ `UpdateChecker.vue` 区分网络/清单/签名/无更新错误。
- ✅ 第八阶段 M4：`scripts/sign_installer.py` 接入 signtool sign/verify + 重新生成 `.sig`（遵循 §2.4 签名顺序）；`build-release.bat` 在 tauri build 与 manifest 之间调用。
- ✅ 无证书透明策略：未设 `PA_CODESIGN_PFX` 时不阻塞构建，写 `dist/unsigned-note-<version>.md`（SmartScreen 说明）+ `dist/codesign-status-<version>.json`（`code_signed: false`），release manifest 标记 `code_signed: no`。
- ✅ SignPath OSS 前置：Apache-2.0、隐私政策、Code signing policy、主仓库 updater 地址和 GitHub 托管可信构建工作流已就绪。
- ⏳ SignPath 外部步骤：等待基金会审核、SignPath 项目/策略创建、GitHub App 授权和首次人工批准签名。
- ✅ 本地证书回退：如以后自备证书，设置 `PA_CODESIGN_PFX` / `PA_CODESIGN_PASSWORD[_FILE]` / `PA_CODESIGN_TIMESTAMP` 仍可自动走 signtool 实签流程。
