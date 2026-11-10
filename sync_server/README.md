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

所有接口都要 `Authorization: Bearer <token>`；服务只保存 token 的 sha256 摘要，不保存
token 本身。**建空间也要 token**：空间 id 由客户端生成，客户端能先派生出 token 再建空间，
匿名调用者不能把服务塞满空间。

## 边界

- 服务**不做**明文合并：每台设备只写自己那份密文，合并发生在客户端。
- 服务**不**知道 master key，因此读不到密文，也做不了「找回」。
- **空间是互信组**：同一空间的设备共享 master key，任何一台都能写别的设备的 blob。
- 单 blob ≤ 8 MB，单空间 ≤ 10 台设备 / 64 MB。
- 标识符只接受 32 位小写 ASCII 十六进制，其余一律拒绝。
- 拒绝带 `Origin` 的请求（浏览器）和不在 Host 白名单内的请求；白名单默认是绑定地址，
  部署在反向代理后面时用 `--allowed-host example.com` 追加。
- 数据库文件按 0600 创建。
- 服务**没有限速**；放到公网前必须补。

## 测试

```sh
python3 -m unittest discover -s sync_server/tests -t .
```

测试全部在 loopback 上跑，不访问外网。
