# 岩芯层段划分与取样封签

砾衡地勘队为 4 台钻机、6 位编录员提供现场岩芯编录。上游是钻进回次和物性测量，下游是岩土实验室收样与成果柱状图。系统解决缺芯被当成测量值、切样区间与配额冲突、断签后历史来源丢失这三类问题。全部演示数据为模拟数据。

## 启动

```bash
cp .env.example .env
docker compose up -d --build --wait
```

前端 `http://localhost:18232`，API `http://localhost:19232/docs`，PostgreSQL `localhost:17732`。在包含中文和空格的目录可直接启动。Compose 恰有 frontend/backend/worker/db/redis 五服务；数据库、Redis、模型心跳共享卷持久化。`.env.example` 提供项目名、端口、子网及 JWT 配置；对外使用前更换演示口令及 JWT_SECRET。

三个账号为 `operator@liheng.local`、`supervisor@liheng.local`、`viewer@liheng.local`，口令均为 `Core2026!`。operator 编录、申请切样、封签交接、编制草稿；supervisor 另可确认层面、撤回解释、报告破签、冻结版本；viewer 只读，后端独立拒绝所有写入。

## 六个业务模块

| 模块 | 领域规则与状态 |
|---|---|
| 钻孔与进尺回次 | Borehole 与 CoreRun；回次不能重叠，回收长度不得超过进尺，孔深内登记；冻结孔禁止修改 |
| 岩芯测点与缺失区间 | Reading 属于本孔回次，孔内深度唯一；缺失区间不能覆盖实测点，不生成假值；说明后由 observed 变 annotated |
| 层段候选与人工接触面 | Interpretation queued→ready/failed→confirmed；人工层段从孔口连续到终孔、每层附依据；一孔只能一份已确认解释 |
| 取样配额与区间冲突 | SampleInterval 必须落在同一已确认层，不穿缺段；破坏性切样不可重叠且合计不超孔配额；planned 可改或取消，封签后不可改 |
| 样袋封签及交接 | planned→sealed→transferred；破签转 broken，只能带原因重封；Seal.previous_id 保存旧链，Custody 只接收当前完整封签且一次一回执 |
| 柱状图版本冻结 | draft→frozen；检查进尺、每米中心测点或明示缺段、缺段说明、层面、所有有效样品交接；冻结保存完整快照并关闭整孔写入 |

取样与配额写入、封签、交接、冻结统一先锁父钻孔，数据库唯一约束作为补充。并发验收主动持有父锁，让两次请求确实竞争，避免仅顺序调用。

## 演示一天

1. 查看 BH-31 两个回次 0–18 / 18–36m 和各回收率，核对孔口位置。
2. 查看 35 个物性点和 12–13m 缺芯；缺芯保留为空段并登记原因。
3. 运行 GMM，查看训练集 BIC 和留出稳定性；按现场纹理编辑 0–12/12–24/24–36m 三个人工层段并主管确认。
4. 在第一层申请 2–3m 切样；8.5–9.5m 与历史 8–9m 切样冲突会被拒绝。改区间后恢复。
5. 旧封签 CX031-001 已破签，不能移交；填原因重封并保持 previous_id，再登记实验室接收人、目的地、完整性。
6. 新样封签后不再允许改区间。主管报告破签后，重新封签、重新交接，历史回执不被覆盖。
7. 建柱状图草稿；未说明缺芯或未交接样品会阻止冻结，补说明/补交接后可重试同一草稿。
8. 冻结版本查看孔深、人工岩性、缺芯带与样品标记；快照保留测点、模型证据、全部封签及交接链。

## 真实 Python 算法

worker 经 Redis 队列执行 `layer_model.py`。密度、磁化率、声速先按 random_state=42 划分 80% 训练和 20% 留出，StandardScaler 只拟合训练集，GaussianMixture 在训练集测试 k=1..5（小样本受训练数约束），按训练 BIC 最小选择成分。固定 seed42、n_init=5、reg_covar=0.01。所有点获得后验与成分，按密度中心排序展示；相邻分类改变给出候选接触面，最终岩性和界面由人解释。

训练集 bootstrap 重新拟合后，在同一留出点比较分类的 ARI，另存留出平均对数似然、训练/留出点 ID、源数据 SHA256。35 点验收得到训练28/留出7、k=3、BIC=-50.406821、稳定性 ARI=1.0、留出平均对数似然2.333906。ARI 是无监督重采样稳定性，不是岩性识别准确率。恒定物性会真实失败，撤回后补测再拟合可以恢复。

## 结构和开发

`backend/src/models.py` 定义关系表；`schemas.py` 提供严格校验与非有限值拒绝；五个领域 service 承担约束；`routes.py` 管接口与角色；`layer_model.py` / `worker.py` 管计算；`common.py` 管父锁与审计。`middlewares.py` 提供请求追踪及异常恢复两层中间件。`frontend/src/pages/` 六页分别实现领域任务，`components/logbook.js` 共用孔头、深度带、徽标等组件，`constants.js` 集中角色和状态，`utils/` 管请求及转义。原生 HTML/CSS/ES modules，无前端框架。

```bash
docker compose exec -T backend python /app/scripts/seed_demo.py
docker compose exec -T backend python /app/scripts/seed_demo.py
docker compose logs worker
docker compose down -v --remove-orphans
```

seed 按自然键填充账号，演示孔不存在时才创建业务数据；已有编辑与冻结快照保持原样。验收脚本、真实截图和测试报告在交付根目录 `test-artifacts/gb-1033`，不混入本源码。

## 边界

这是单团队小型演示，冻结后整孔关闭，没有修订解冻入口；冻结覆盖检查采用每米中心点网格，非任意连续精度测量协议。没有仪器文件导入、外部地质真值、电子签章和多组织隔离。Redis BLPOP 为轻量队列，已弹出任务遇进程被杀不会自动重投；正常计算失败会存 failed 与原因，可撤回补测重跑。手动接触面不修改既有历史取样的来源层。`create_all` 用于新库演示，无生产迁移系统。

License: MIT，适用于本项目新增源码。
