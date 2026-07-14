import { useCallback, useState } from 'react'
import { App, Drawer, Input, Switch, Table, Button, Popconfirm, Tag } from 'antd'
import { Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  aiProviderApi,
  normalizeProviderKeyList,
  type AiProviderDefinition,
  type AiProviderKey,
} from '@/api/ai/providers'
import { AsyncSection } from '@/components/common/AsyncSection'
import { maskApiKey } from '@/config/modelVendors'
import './ProviderKeysDrawer.css'

interface ProviderKeysDrawerProps {
  open: boolean
  provider: AiProviderDefinition | null
  onClose: () => void
}

interface KeyTableRow {
  rowKey: string
  id?: number
  remark: string
  api_key: string
  status: boolean
  isDraft: boolean
  saving?: boolean
}

function createDraftRow(): KeyTableRow {
  return {
    rowKey: `draft-${Date.now()}`,
    remark: '',
    api_key: '',
    status: true,
    isDraft: true,
  }
}

function toTableRows(keys: AiProviderKey[]): KeyTableRow[] {
  return keys.map((key) => ({
    rowKey: String(key.id),
    id: key.id,
    remark: key.remark ?? '',
    api_key: key.api_key ?? '',
    status: key.status !== false,
    isDraft: false,
  }))
}

export function ProviderKeysDrawer({ open, provider, onClose }: ProviderKeysDrawerProps) {
  const { t } = useTranslation()
  const { message } = App.useApp()
  const [rows, setRows] = useState<KeyTableRow[]>([])
  const [keysLoading, setKeysLoading] = useState(false)
  const [keysError, setKeysError] = useState<string | null>(null)

  const providerCode = provider?.code

  const loadKeys = useCallback(async () => {
    if (!providerCode) {
      setRows([])
      return
    }

    setKeysLoading(true)
    setKeysError(null)
    try {
      const data = await aiProviderApi.listKeys(providerCode, { page: 1, page_size: 100 })
      setRows(toTableRows(normalizeProviderKeyList(data)))
    } catch (err) {
      setKeysError(err instanceof Error ? err.message : t('common.loadFailed'))
    } finally {
      setKeysLoading(false)
    }
  }, [providerCode, t])

  const handleAfterOpenChange = (visible: boolean) => {
    if (visible && providerCode) {
      void loadKeys()
    }
  }

  const handleClose = () => {
    setRows([])
    setKeysError(null)
    onClose()
  }

  const updateRow = useCallback((rowKey: string, patch: Partial<KeyTableRow>) => {
    setRows((prev) => prev.map((row) => (row.rowKey === rowKey ? { ...row, ...patch } : row)))
  }, [])

  const handleSaveDraft = useCallback(async (row: KeyTableRow) => {
    if (!providerCode) return
    if (!row.api_key.trim()) {
      message.warning(t('settings.models.apiKeyRequired'))
      return
    }

    updateRow(row.rowKey, { saving: true })
    try {
      await aiProviderApi.createKey(providerCode, {
        api_key: row.api_key.trim(),
        remark: row.remark.trim() || undefined,
        status: row.status,
      })
      message.success(t('settings.models.keyAdded'))
      await loadKeys()
    } catch (err) {
      message.error(err instanceof Error ? err.message : t('common.loadFailed'))
      updateRow(row.rowKey, { saving: false })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 为 antd 稳定引用
  }, [loadKeys, providerCode, t, updateRow])

  const handleRemoveDraft = useCallback((rowKey: string) => {
    setRows((prev) => prev.filter((row) => row.rowKey !== rowKey))
  }, [])

  const handleRemove = useCallback(async (keyId: number) => {
    try {
      await aiProviderApi.deleteKey(keyId)
      message.success(t('settings.models.keyRemoved'))
      await loadKeys()
    } catch (err) {
      message.error(err instanceof Error ? err.message : t('common.loadFailed'))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 为 antd 稳定引用
  }, [loadKeys, t])

  const handleAddDraftRow = () => {
    setRows((prev) => {
      if (prev.some((row) => row.isDraft)) {
        return prev
      }
      return [...prev, createDraftRow()]
    })
  }

  const columns = [
    {
      title: t('settings.models.colKeyAlias'),
      dataIndex: 'remark',
      key: 'remark',
      width: 160,
      render: (_: unknown, record: KeyTableRow) =>
        record.isDraft ? (
          <Input
            size="small"
            value={record.remark}
            placeholder={t('settings.models.keyAliasPlaceholder')}
            onChange={(e) => updateRow(record.rowKey, { remark: e.target.value })}
          />
        ) : (
          <span>{record.remark || '—'}</span>
        ),
    },
    {
      title: t('settings.models.colApiKey'),
      key: 'api_key',
      render: (_: unknown, record: KeyTableRow) =>
        record.isDraft ? (
          <Input.Password
            size="small"
            value={record.api_key}
            placeholder="sk-..."
            onChange={(e) => updateRow(record.rowKey, { api_key: e.target.value })}
          />
        ) : (
          <code className="provider-keys__key">{maskApiKey(record.api_key)}</code>
        ),
    },
    {
      title: t('settings.models.colStatus'),
      dataIndex: 'status',
      key: 'status',
      width: 88,
      render: (status: boolean, record: KeyTableRow) =>
        record.isDraft ? (
          <Switch
            size="small"
            checked={status}
            onChange={(checked) => updateRow(record.rowKey, { status: checked })}
          />
        ) : (
          <Tag color={status ? 'blue' : 'default'}>
            {status ? t('settings.apiTest.statusOn') : t('settings.apiTest.statusOff')}
          </Tag>
        ),
    },
    {
      title: t('settings.models.colActions'),
      key: 'actions',
      width: 120,
      render: (_: unknown, record: KeyTableRow) =>
        record.isDraft ? (
          <div className="provider-keys__actions">
            <Button
              type="link"
              size="small"
              loading={record.saving}
              onClick={() => void handleSaveDraft(record)}
            >
              {t('common.save')}
            </Button>
            <Button
              type="link"
              size="small"
              onClick={() => handleRemoveDraft(record.rowKey)}
            >
              {t('common.cancel')}
            </Button>
          </div>
        ) : (
          <Popconfirm
            title={t('settings.models.confirmRemoveKey')}
            onConfirm={() => record.id && void handleRemove(record.id)}
          >
            <Button type="link" size="small" danger>
              {t('common.delete')}
            </Button>
          </Popconfirm>
        ),
    },
  ]

  return (
    <Drawer
      title={
        provider
          ? t('settings.models.manageVendorKeys', { vendor: provider.name })
          : ''
      }
      open={open}
      onClose={handleClose}
      afterOpenChange={handleAfterOpenChange}
      size={720}
      destroyOnHidden
      extra={
        <Button size="small" icon={<Plus size={13} />} onClick={handleAddDraftRow}>
          {t('settings.models.addKey')}
        </Button>
      }
    >
      <p className="provider-keys__hint">{t('settings.models.multiKeyHint')}</p>

      <AsyncSection
        loading={keysLoading && rows.length === 0}
        error={keysError}
        onRetry={() => void loadKeys()}
        minHeight={120}
      >
        <Table<KeyTableRow>
          size="small"
          rowKey="rowKey"
          columns={columns}
          dataSource={rows}
          pagination={false}
          loading={keysLoading && rows.length > 0}
          locale={{ emptyText: t('settings.models.noKeysYet') }}
          rowClassName={(record) =>
            record.isDraft ? 'provider-keys__row--draft' : 'provider-keys__row--readonly'
          }
          className="provider-keys__table provider-keys__table--editable"
        />
      </AsyncSection>
    </Drawer>
  )
}
