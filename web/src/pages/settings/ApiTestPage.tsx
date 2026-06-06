import { useCallback, useMemo } from 'react'
import { Button, Descriptions, Table, Tag } from 'antd'
import { useTranslation } from 'react-i18next'
import { aiModelApi, AI_GATEWAY_PROXY_TARGET, API_BASE_URL, normalizeModelList, XQTRADER_PROXY_TARGET, type AiModelItem } from '@/api'
import { AsyncSection } from '@/components/common/AsyncSection'
import { useRequest } from '@/hooks/useRequest'
import '@/styles/pages.css'
import './ApiTestPage.css'

export function ApiTestPage() {
  const { t } = useTranslation()

  const fetchModels = useCallback(
    () => aiModelApi.list({ page: 1, page_size: 20 }),
    [],
  )

  const { data, loading, error, reload } = useRequest(fetchModels)

  const rows = useMemo(() => normalizeModelList(data), [data])

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 80,
    },
    {
      title: t('settings.apiTest.colName'),
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: t('settings.apiTest.colType'),
      dataIndex: 'type',
      key: 'type',
    },
    {
      title: t('settings.apiTest.colStatus'),
      dataIndex: 'status',
      key: 'status',
      render: (status: boolean | undefined) =>
        status === undefined ? '—' : (
          <Tag color={status ? 'blue' : 'default'}>
            {status ? t('settings.apiTest.statusOn') : t('settings.apiTest.statusOff')}
          </Tag>
        ),
    },
  ]

  return (
    <div className="api-test-page">
      <div className="card">
        <div className="card__header">
          <h3 className="card__title">{t('settings.nav.apiTest')}</h3>
          <Button size="small" onClick={() => void reload()} loading={loading}>
            {t('common.retry')}
          </Button>
        </div>

        <Descriptions size="small" column={1} className="api-test-page__meta">
          <Descriptions.Item label={t('settings.apiTest.endpoint')}>
            <code>{API_BASE_URL}/ai/models?page=1&amp;page_size=20</code>
          </Descriptions.Item>
          <Descriptions.Item label={t('settings.apiTest.proxyAi')}>
            <code>/api/v1/ai、/v1 → {AI_GATEWAY_PROXY_TARGET}</code>
          </Descriptions.Item>
          <Descriptions.Item label={t('settings.apiTest.proxyPlatform')}>
            <code>/api → {XQTRADER_PROXY_TARGET}</code>
          </Descriptions.Item>
        </Descriptions>

        <AsyncSection loading={loading} error={error} onRetry={() => void reload()} minHeight={200}>
          <Table<AiModelItem>
            size="small"
            rowKey={(row, index) => String(row.id ?? index)}
            columns={columns}
            dataSource={rows}
            pagination={false}
            locale={{ emptyText: t('settings.apiTest.empty') }}
          />
          {data && (
            <pre className="api-test-page__raw">{JSON.stringify(data, null, 2)}</pre>
          )}
        </AsyncSection>
      </div>
    </div>
  )
}
