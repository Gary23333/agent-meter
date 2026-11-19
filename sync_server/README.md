# AgentMeter 同步服务（开发版）

一个只存**密文**的同步服务。客户端在数据离开本机之前就把它加密了，所以服务
运营方读不到自己保存的内容——服务只知道「某个空间里有几个设备，各传了多大
的密文」。

这是 M0 的骨架版本：空间、设备 blob、空间清单。会员、许可证与支付不在本文件
范围内。

## 跑起来

```sh
python3 sync_server/app.py --db .runtime/sync-server.db --port 8899
```

默认只监听 `127.0.0.1`。对外暴露是部署决定，前置传输必须是 https；部署在反向代理
后面时用 `--allowed-host example.com` 追加 Host 白名单。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/health` | 存活检查 |
| POST | `/v1/sync/spaces` | 建空间，body `{"space_id": "<32 hex>", "auth_hash": "<sha256 hex>"}`，返回 `{"space_id": ...}` |
| GET | `/v1/sync/{space_id}` | 空间清单：各设备的 `device_id / size / version / updated_at`（不含内容） |
| GET | `/v1/sync/{space_id}/{device_id}` | 取回某设备的密文（原始字节） |
| PUT | `/v1/sync/{space_id}/{device_id}` | 上传本设备的密文（原始字节，≤ 8 MB） |
| DELETE | `/v1/sync/{space_id}/{device_id}` | 删除本设备的密文 |

所有 `/v1/sync/*` 接口都要 `Authorization: Bearer <token>`；服务只保存 token 的 sha256
摘要，不保存 token 本身。**建空间也要 token**：空间 id 由客户端生成，客户端能先派生出
token 再建空间，匿名调用者不能把服务塞满空间。

## 短码配对

短码只用来**定位一个一次性槽位**，不承载密钥。主密钥始终在发起端，服务只中转两台
设备的临时公钥和一段密文。

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/v1/pair/slots` | 空间 token | body `{"space_id", "pub_a"}`，返回 6 位 `code`、`slot_id`、`expires_at` |
| POST | `/v1/pair/lookup` | 匿名（按 IP 限速） | body `{"code"}`，返回 `slot_id / space_id / pub_a / join_token` |
| PUT | `/v1/pair/slots/{slot_id}` | join token | 加入端上传 `{"pub_b"}`，只上传公钥 |
| GET | `/v1/pair/slots/{slot_id}` | 空间 token | 发起端轮询 `pub_b`；`ready: true` 后可封密钥 |
| PUT | `/v1/pair/slots/{slot_id}/sealed` | 空间 token | 发起端上传 `{"ciphertext"}`，即封装后的主密钥 |
| GET | `/v1/pair/slots/{slot_id}/sealed` | join token | 加入端轮询密文；`ready: true` 后解密 |
| DELETE | `/v1/pair/slots/{slot_id}` | 空间 token | 发起端确认后消费槽位 |

流程：

1. 发起端已有空间与主密钥，生成 X25519 临时密钥对，提交 `pub_a` 换 6 位码。
2. 加入端输码 → 拿到 `pub_a` 与 join token，生成自己的临时密钥对，提交 `pub_b`。
3. 发起端看到 `pub_b`，用 ECDH 共享秘密派生包装密钥，把 `{space_id, master_key}`
   用 ChaChaPoly 封装后上传；加入端取回并解密。
4. 两端都能从共享秘密派生同一个 6 位安全码（SAS），由人核对，防止中间人。

服务端只看得到公钥、密文和槽位状态；**没有主密钥，也没有明文**。短码 5 分钟过期，
单个槽位最多 5 次输码尝试，每 IP 每分钟最多 10 次 lookup，每个空间最多 3 个未消费槽位。
join token 只对当前槽位有效，槽位消费后失效。

## 边界

- 服务**不做**明文合并：每台设备只写自己那份密文，合并发生在客户端。
- 服务**不**知道 master key，因此读不到密文，也做不了「找回」。
- **空间是互信组**：同一空间的设备共享 master key，任何一台都能写别的设备的 blob。
- 单 blob ≤ 8 MB，单空间 ≤ 10 台设备 / 64 MB。
- 标识符只接受 32 位小写 ASCII 十六进制，其余一律拒绝。
- 拒绝带 `Origin` 的请求（浏览器）和不在 Host 白名单内的请求；白名单默认是绑定地址，
  部署在反向代理后面时用 `--allowed-host example.com` 追加。
- 数据库文件按 0600 创建。
- `/v1/pair/lookup` 按 IP 限速；其余写接口目前没有通用限速，放到公网前仍建议在
  Cloudflare 层加规则。

## 放到家里服务器 + Cloudflare Tunnel

服务只监听 loopback，由 `cloudflared` 出站建隧道，不需要公网 IP：

```sh
# 家里服务器
python3 sync_server/app.py --db .runtime/sync-server.db --port 8899 \
  --allowed-host sync.example.com

# 另一台机器 / 同一台机器
cloudflared tunnel --url http://127.0.0.1:8899
```

把隧道给出的 `https://...` 地址（或自己的域名）填进两台 Mac 的「同步服务地址」。
`--allowed-host` 必须写公网访问用的 Host，否则服务会拒绝反向代理转来的请求。
中国大陆访问 Cloudflare 免费版通常走香港/东京/新加坡，延迟明显高于本机；同步是手动
触发的，问题不大。公开收费前仍需补配额、备份与备案，详见
[调研](../docs/research/account-and-hosting-recon-2026-11-19.md)。

## 测试

```sh
python3 -m unittest discover -s sync_server/tests -t .
```

测试全部在 loopback 上跑，不访问外网。
