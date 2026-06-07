# WebSocket Topic 订阅推送系统

## 1. 架构概览

本系统基于 **Topic 发布-订阅模式**，实现后端数据到前端的实时推送。核心设计原则：

- **按需推送**：APScheduler 定时任务按 Topic 订阅状态动态启停，无订阅时不执行
- **单连接多 Topic**：同一页面只建立 1 个 WebSocket 连接，通过订阅多个 Topic 接收不同类型数据
- **SPI 插件化**：每个 Topic 对应一个 SPI 实现类，通过注册中心管理，易于扩展
- **分层解耦**：framework 层提供通用 WS 基础设施，业务层通过回调机制接入，不反向依赖

### 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│  ┌──────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ StatusBar │  │ usePageWebSocket │  │ webSocketManager │  │
│  └─────┬────┘  └────────┬─────────┘  └────────┬─────────┘  │
│        │                │                      │             │
│        └────────────────┼──────────────────────┘             │
│                         │ WebSocket (单连接, 多Topic)         │
└─────────────────────────┼───────────────────────────────────┘
                          │
┌─────────────────────────┼───────────────────────────────────┐
│                    Backend (FastAPI)                          │
│                         │                                    │
│  ┌──────────────────────┼──────────────────────────────┐    │
│  │              ConnectionManager                       │    │
│  │  ┌────────────┐  ┌────────────┐  ┌──────────────┐  │    │
│  │  │ 订阅管理    │  │ 心跳检测    │  │ 回调通知      │  │    │
│  │  │ subscribe/  │  │ ping/pong  │  │ on_subscribed │  │    │
│  │  │ unsubscribe │  │ 25s/60s    │  │ on_unsubscribed│  │    │
│  │  └────────────┘  └────────────┘  └──────┬───────┘  │    │
│  └──────────────────────────────────────────┼──────────┘    │
│                                             │ 回调            │
│  ┌──────────────────────────────────────────┼──────────┐    │
│  │              WsTopicScheduler             │          │    │
│  │  ┌─────────────────────────────────────┐  │          │    │
│  │  │ APScheduler (按订阅动态启停)          │◄─┘          │    │
│  │  │  Topic有订阅 → 启动Job (2s间隔)      │             │    │
│  │  │  Topic无订阅 → 停止Job              │             │    │
│  │  └──────────┬──────────────────────────┘             │    │
│  │             │ 执行SPI                                │    │
│  │  ┌──────────▼──────────────────────────┐             │    │
│  │  │ SpiRegistry (策略注册中心)            │             │    │
│  │  │  ws.broker.status → BrokerStatusSpi │             │    │
│  │  │  ws.trading.pnl   → PnlSpi         │             │    │
│  │  │  (新增Topic → 新增SPI实现类)         │             │    │
│  │  └──────────┬──────────────────────────┘             │    │
│  └─────────────┼────────────────────────────────────────┘    │
│                │ publish_update                               │
│  ┌─────────────▼────────────────────────────────────────┐    │
│  │              WsPublisher                               │    │
│  │  publish → Redis Pub/Sub (ws:topic:{topic})           │    │
│  │         → Redis Snapshot (ws:topic:{topic}:snapshot)  │    │
│  └─────────────┬────────────────────────────────────────┘    │
│                │                                             │
│  ┌─────────────▼────────────────────────────────────────┐    │
│  │              RedisListener (后台线程)                   │    │
│  │  psubscribe("ws:topic:*")                             │    │
│  │  收到消息 → run_coroutine_threadsafe → broadcast      │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

## 2. 数据流

```
SPI.execute() → WsPublisher.publish_update() → Redis Pub/Sub
                                                    │
RedisListener ← psubscribe("ws:topic:*") ←─────────┘
     │
     ▼
ConnectionManager.broadcast_to_topic()
     │
     ▼
WebSocket → 前端 webSocketManager → TopicHandler.onUpdate()
```

## 3. 模块说明

### 3.1 Framework 层 (`src/framework/ws/`)

| 模块 | 类/函数 | 职责 |
|------|---------|------|
| `messages.py` | `WsClientMessage`, `WsServerMessage`, 常量 | 消息协议定义，统一常量管理 |
| `exceptions.py` | `WsError` 及子类 | 领域异常层级 |
| `connection_manager.py` | `ConnectionManager` (单例) | 连接管理、订阅管理、心跳检测、消息路由 |
| `publisher.py` | `WsPublisher` | 消息发布到 Redis Pub/Sub |
| `redis_listener.py` | `RedisListener` (单例) | 后台线程监听 Redis Pub/Sub，转发到本地连接 |
| `ticket_auth.py` | `TicketAuth` | 一次性短令牌认证 |

### 3.2 业务层 (`src/xqtrader/ws/`)

| 模块 | 类/函数 | 职责 |
|------|---------|------|
| `constants.py` | `WsTopic` | Topic 名称常量 |
| `scheduler.py` | `WsTopicScheduler` | APScheduler 调度器，按订阅动态启停 |
| `handler.py` | `WsHandler` | WebSocket 连接处理入口 |
| `router.py` | `ws_router`, `ticket_router` | FastAPI 路由注册 |
| `spi/__init__.py` | `TopicSpi`, `SpiRegistry` | SPI 基类与注册中心 |
| `spi/impl/broker_status.py` | `BrokerStatusSpi` | QMT 行情+交易连接状态 |
| `spi/impl/pnl.py` | `PnlSpi` | QMT 账户资产查询 |

### 3.3 前端 (`web/src/ws/`)

| 模块 | 职责 |
|------|------|
| `protocol.ts` | 消息类型定义、Topic 常量、Ticket 获取 |
| `webSocketManager.ts` | WebSocket 连接管理（单例），引用计数、自动连接/断开、断线重连 |
| `usePageWebSocket.ts` | React Hook，页面级 Topic 订阅管理 |

## 4. 消息协议

### 4.1 客户端 → 服务端

```json
// 订阅 Topic
{ "method": "SUBSCRIBE", "params": ["ws.broker.status", "ws.trading.pnl"], "id": 1 }

// 取消订阅
{ "method": "UNSUBSCRIBE", "params": ["ws.trading.pnl"], "id": 2 }

// 心跳（响应服务端 PING）
{ "method": "PING", "id": 3 }

// 查询当前订阅
{ "method": "LIST_SUBSCRIPTIONS", "id": 4 }
```

### 4.2 服务端 → 客户端

```json
// 增量更新
{ "type": "UPDATE", "channel": "ws.broker.status", "data": {...} }

// 快照
{ "type": "SNAPSHOT", "channel": "ws.broker.status", "data": {...} }

// 订阅确认
{ "type": "ACK", "id": 1, "data": ["ws.broker.status", "ws.trading.pnl"] }

// 心跳
{ "type": "PING" }

// 心跳响应
{ "type": "PONG", "id": 3 }

// 查询结果
{ "type": "RESULT", "id": 4, "data": ["ws.broker.status"] }

// 错误
{ "type": "ERROR", "id": 1, "code": "INVALID_MESSAGE", "message": "..." }
```

## 5. Topic 定义

| Topic 常量 | 值 | 说明 | 数据字段 |
|------------|-----|------|----------|
| `WsTopic.BROKER_STATUS` | `ws.broker.status` | 行情+交易连接状态 | `market_status`, `trading_status`, `timestamp` |
| `WsTopic.TRADING_PNL` | `ws.trading.pnl` | 账户资产 | `cash`, `frozen_cash`, `market_value`, `total_asset`, `reason?`, `timestamp` |

## 6. 心跳机制

- **服务端主动 PING**：每 25 秒向所有连接发送 `{ "type": "PING" }`
- **客户端回复 PONG**：收到 PING 后发送 `{ "method": "PING", "id": ... }`
- **超时断开**：60 秒内无任何消息活动（包括 PONG），服务端主动断开连接
- **断线重连**：客户端检测到连接关闭后，1.5 秒后自动重连并重新订阅

## 7. 认证机制

采用 **Ticket 一次性短令牌** 认证：

1. 前端调用 `POST /api/v1/ws/ticket` 获取 ticket
2. 建立 WebSocket 连接时通过 URL 参数传递：`ws://host/ws?ticket=xxx`
3. 服务端验证 ticket 后立即删除（一次性使用），ticket 有效期 5 分钟
4. 后续可替换为 JWT 用户认证

## 8. 动态调度

APScheduler 任务按 Topic 订阅状态动态启停：

| 事件 | 动作 |
|------|------|
| 有连接订阅 Topic | `ConnectionManager` 回调 → `WsTopicScheduler.on_topic_subscribed()` → 添加 APScheduler Job |
| 所有连接取消订阅 Topic | `ConnectionManager` 回调 → `WsTopicScheduler.on_topic_unsubscribed()` → 移除 APScheduler Job |
| WebSocket 断开 | `ConnectionManager.disconnect()` → 清理所有订阅 → 触发无订阅的 Topic 停止 Job |

## 9. 扩展新 Topic

### 后端

1. 在 `src/xqtrader/ws/constants.py` 添加 Topic 常量：

```python
class WsTopic:
    BROKER_STATUS = "ws.broker.status"
    TRADING_PNL = "ws.trading.pnl"
    NEW_TOPIC = "ws.new.topic"  # 新增
```

2. 在 `src/xqtrader/ws/spi/impl/` 下新建文件，实现 SPI：

```python
from framework.ws.exceptions import WsSpiError
from xqtrader.ws.constants import WsTopic
from .. import TopicSpi, register_spi

@register_spi
class NewTopicSpi(TopicSpi):
    @property
    def topic_name(self) -> str:
        return WsTopic.NEW_TOPIC

    def execute(self) -> dict:
        # 实现数据获取逻辑
        return {"key": "value", "timestamp": time.time()}
```

3. 在 `src/xqtrader/ws/spi/impl/__init__.py` 中导入以触发注册：

```python
from .new_topic import NewTopicSpi  # noqa: F401
```

### 前端

1. 在 `web/src/ws/protocol.ts` 添加 Topic 常量和数据类型：

```typescript
export const TOPIC_NEW_TOPIC = 'ws.new.topic'

export interface NewTopicData {
  key: string
  timestamp: number
}
```

2. 在页面组件中使用 `usePageWebSocket` 订阅：

```typescript
const [data, setData] = useState<NewTopicData | null>(null)
usePageWebSocket<NewTopicData>({
  topics: [TOPIC_NEW_TOPIC],
  onUpdate: (_channel, data) => setData(data),
})
```

## 10. API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/ws` | WebSocket | WebSocket 连接入口，URL 参数 `ticket` 认证 |
| `/api/v1/ws/ticket` | POST | 生成一次性 Ticket，返回 `{ ticket, expires_in }` |
