-- ============================================================
-- 007: 研报 / 新闻公告 / 舆情快照表 — stock schema
-- ============================================================
-- 背景:
--   为 agent skill 体系（sentiment-analysis / stock-analysis / compare-analysis）
--   提供结构化数据底座，替代直接抓取网页。
--   数据源：
--     - 研报：东方财富研报中心 HTTP API（reportapi.eastmoney.com）
--     - 新闻/公告：akshare stock_news_em / stock_individual_notice_report
--     - 舆情：akshare stock_js_weibo_report
--
-- 表结构:
--   1. stock.sdc_research_report   — 券商研报元数据 + PDF 路径
--   2. stock.sdc_stock_news        — 个股新闻与公告（news_type 区分）
--   3. stock.sdc_stock_sentiment   — 市场舆情快照（按日聚合）
--
-- 设计要点:
--   - 三张表均继承 AuditedBase，自带 id / created_at / updated_at 审计字段
--   - 表名统一 sdc_ 前缀，与 stock schema 下其它表一致
--   - 唯一约束：研报 info_code / 新闻 news_url / 舆情 (snapshot_date, sentiment_type, symbol)
--     舆情表 symbol 列 NOT NULL DEFAULT ''（市场级舆情用空串占位），保证复合唯一约束可正确去重
--   - JSONB 字段：盈利预测 / 关键词列表 / 热门关键词
-- ============================================================

BEGIN;

-- ============================================================
-- 1. 券商研报表 — stock.sdc_research_report
-- ============================================================
CREATE TABLE IF NOT EXISTS stock.sdc_research_report (
    id              BIGSERIAL PRIMARY KEY,
    info_code       VARCHAR(64)  NOT NULL,
    symbol          VARCHAR(20),
    title           VARCHAR(255) NOT NULL,
    org_name        VARCHAR(64),
    researcher      VARCHAR(128),
    rating          VARCHAR(16),
    rating_change   VARCHAR(16),
    publish_date    DATE,
    industry        VARCHAR(64),
    eps_forecast    JSONB,
    pdf_url         VARCHAR(512),
    pdf_path        VARCHAR(512),
    summary         TEXT,
    content         TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_sdc_research_report_info_code UNIQUE (info_code)
);

COMMENT ON TABLE  stock.sdc_research_report IS '券商研报表 — 东财研报中心采集产物';
COMMENT ON COLUMN stock.sdc_research_report.info_code     IS '东财研报唯一标识（如 AP202606291826552423）';
COMMENT ON COLUMN stock.sdc_research_report.symbol        IS '标的代码（行业研报可空）';
COMMENT ON COLUMN stock.sdc_research_report.title         IS '研报标题';
COMMENT ON COLUMN stock.sdc_research_report.org_name      IS '研究机构名称';
COMMENT ON COLUMN stock.sdc_research_report.researcher    IS '分析师姓名';
COMMENT ON COLUMN stock.sdc_research_report.rating        IS '评级（买入/增持/中性/减持/卖出）';
COMMENT ON COLUMN stock.sdc_research_report.rating_change IS '评级变动（首次/维持/调高/调低）';
COMMENT ON COLUMN stock.sdc_research_report.publish_date  IS '研报发布日期';
COMMENT ON COLUMN stock.sdc_research_report.industry      IS '所属行业';
COMMENT ON COLUMN stock.sdc_research_report.eps_forecast  IS '盈利预测 JSONB（年度/EPS/PE 数组）';
COMMENT ON COLUMN stock.sdc_research_report.pdf_url       IS '研报 PDF 下载链接';
COMMENT ON COLUMN stock.sdc_research_report.pdf_path      IS '本地 PDF 相对路径（相对 WORKSPACE_ROOT）';
COMMENT ON COLUMN stock.sdc_research_report.summary       IS '研报摘要';
COMMENT ON COLUMN stock.sdc_research_report.content       IS '研报全文（从 PDF 解析，可选）';

CREATE INDEX IF NOT EXISTS idx_sdc_research_report_symbol        ON stock.sdc_research_report (symbol);
CREATE INDEX IF NOT EXISTS idx_sdc_research_report_publish_date  ON stock.sdc_research_report (publish_date);
CREATE INDEX IF NOT EXISTS idx_sdc_research_report_org_name      ON stock.sdc_research_report (org_name);

-- ============================================================
-- 2. 个股新闻与公告表 — stock.sdc_stock_news
-- ============================================================
CREATE TABLE IF NOT EXISTS stock.sdc_stock_news (
    id              BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(20)  NOT NULL,
    news_type       VARCHAR(16)  NOT NULL,
    title           VARCHAR(255) NOT NULL,
    content         TEXT,
    source          VARCHAR(64),
    news_url        VARCHAR(512) NOT NULL,
    publish_time    TIMESTAMPTZ,
    keywords        JSONB,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_sdc_stock_news_url UNIQUE (news_url)
);

COMMENT ON TABLE  stock.sdc_stock_news IS '个股新闻与公告表 — akshare 采集产物';
COMMENT ON COLUMN stock.sdc_stock_news.symbol       IS '标的代码';
COMMENT ON COLUMN stock.sdc_stock_news.news_type    IS '类型：news=新闻 / announcement=公告';
COMMENT ON COLUMN stock.sdc_stock_news.title        IS '标题';
COMMENT ON COLUMN stock.sdc_stock_news.content      IS '正文内容';
COMMENT ON COLUMN stock.sdc_stock_news.source       IS '来源（如东方财富/巨潮网）';
COMMENT ON COLUMN stock.sdc_stock_news.news_url     IS '原文链接（唯一键，URL 去重）';
COMMENT ON COLUMN stock.sdc_stock_news.publish_time IS '发布时间';
COMMENT ON COLUMN stock.sdc_stock_news.keywords     IS '关键词列表 JSONB（字符串数组）';

CREATE INDEX IF NOT EXISTS idx_sdc_stock_news_symbol        ON stock.sdc_stock_news (symbol);
CREATE INDEX IF NOT EXISTS idx_sdc_stock_news_news_type     ON stock.sdc_stock_news (news_type);
CREATE INDEX IF NOT EXISTS idx_sdc_stock_news_publish_time  ON stock.sdc_stock_news (publish_time);

-- ============================================================
-- 3. 市场舆情快照表 — stock.sdc_stock_sentiment
-- ============================================================
CREATE TABLE IF NOT EXISTS stock.sdc_stock_sentiment (
    id                BIGSERIAL PRIMARY KEY,
    symbol            VARCHAR(20)  NOT NULL DEFAULT '',
    snapshot_date     DATE         NOT NULL,
    sentiment_type    VARCHAR(32)  NOT NULL,
    heat_score        DOUBLE PRECISION,
    sentiment_score   DOUBLE PRECISION,
    positive_count    INTEGER,
    negative_count    INTEGER,
    neutral_count     INTEGER,
    keywords          JSONB,
    summary           TEXT,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_sdc_stock_sentiment_date_type_symbol
        UNIQUE (snapshot_date, sentiment_type, symbol)
);

COMMENT ON TABLE  stock.sdc_stock_sentiment IS '市场舆情快照表 — akshare 舆情接口采集产物';
COMMENT ON COLUMN stock.sdc_stock_sentiment.symbol          IS '标的代码（市场级舆情为空串占位）';
COMMENT ON COLUMN stock.sdc_stock_sentiment.snapshot_date   IS '快照日期';
COMMENT ON COLUMN stock.sdc_stock_sentiment.sentiment_type  IS '舆情类型：weibo=微博/market=市场/stock=个股';
COMMENT ON COLUMN stock.sdc_stock_sentiment.heat_score      IS '热度评分（0-100）';
COMMENT ON COLUMN stock.sdc_stock_sentiment.sentiment_score IS '情感评分（-1~1，负=消极/正=积极）';
COMMENT ON COLUMN stock.sdc_stock_sentiment.positive_count  IS '正面提及数';
COMMENT ON COLUMN stock.sdc_stock_sentiment.negative_count  IS '负面提及数';
COMMENT ON COLUMN stock.sdc_stock_sentiment.neutral_count   IS '中性提及数';
COMMENT ON COLUMN stock.sdc_stock_sentiment.keywords        IS '热门关键词 JSONB（word/count 对象数组）';
COMMENT ON COLUMN stock.sdc_stock_sentiment.summary         IS '舆情摘要';

CREATE INDEX IF NOT EXISTS idx_sdc_stock_sentiment_snapshot_date  ON stock.sdc_stock_sentiment (snapshot_date);
CREATE INDEX IF NOT EXISTS idx_sdc_stock_sentiment_sentiment_type ON stock.sdc_stock_sentiment (sentiment_type);

COMMIT;
