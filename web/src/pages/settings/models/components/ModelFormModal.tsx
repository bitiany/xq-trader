import { Form, Input, Modal, Radio, Select, Switch } from 'antd'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import type { AiModelItem, CreateModelPayload } from '@/api/ai/models'
import type { AiProviderDefinition } from '@/api/ai/providers'
import { MODEL_TYPES } from '@/config/modelVendors'
import './ModelFormModal.css'

export interface ModelFormValues extends CreateModelPayload {
  provider_code?: string
}

interface ModelFormModalProps {
  open: boolean
  editing?: AiModelItem | null
  providers: AiProviderDefinition[]
  onCancel: () => void
  onSubmit: (values: ModelFormValues) => Promise<void>
}

export function ModelFormModal({
  open,
  editing,
  providers,
  onCancel,
  onSubmit,
}: ModelFormModalProps) {
  const { t } = useTranslation()
  const [form] = Form.useForm<ModelFormValues>()
  const isEdit = !!editing?.id

  useEffect(() => {
    if (open && editing) {
      form.setFieldsValue({
        name: editing.name ?? '',
        type: editing.type ?? 'chat',
        description: (editing.description as string) ?? '',
        status: editing.status !== false,
      })
    } else if (open) {
      form.setFieldsValue({ type: 'chat', status: true, provider_code: undefined })
    }
  }, [open, editing, form])

  const handleFinish = async (values: ModelFormValues) => {
    await onSubmit(values)
    form.resetFields()
  }

  return (
    <Modal
      title={isEdit ? t('settings.models.editModel') : t('settings.models.createModel')}
      open={open}
      onCancel={onCancel}
      onOk={() => form.submit()}
      destroyOnHidden
      okText={t('common.save')}
      cancelText={t('common.cancel')}
      width={520}
    >
      <Form<ModelFormValues> form={form} layout="vertical" onFinish={(v) => void handleFinish(v)}>
        <Form.Item
          name="name"
          label={t('settings.models.colName')}
          rules={[{ required: true, message: t('settings.models.nameRequired') }]}
        >
          <Input placeholder="gpt-4o / qwen-max" />
        </Form.Item>
        <Form.Item name="type" label={t('settings.models.colType')} rules={[{ required: true }]}>
          <Select
            options={MODEL_TYPES.map((type) => ({
              value: type,
              label: t(`settings.models.types.${type}`),
            }))}
          />
        </Form.Item>
        {!isEdit && (
          <Form.Item
            name="provider_code"
            label={t('settings.models.selectProvider')}
            rules={[{ required: true, message: t('settings.models.selectProviderRequired') }]}
          >
            <Radio.Group className="model-form__providers">
              {providers.map((provider) => (
                <Radio key={provider.code} value={provider.code} className="model-form__provider">
                  <span className="model-form__provider-icon">{provider.icon ?? '•'}</span>
                  <span className="model-form__provider-name">{provider.name}</span>
                </Radio>
              ))}
            </Radio.Group>
          </Form.Item>
        )}
        <Form.Item name="description" label={t('settings.models.descriptionLabel')}>
          <Input.TextArea rows={2} placeholder={t('settings.models.descriptionPlaceholder')} />
        </Form.Item>
        <Form.Item name="status" label={t('settings.models.colStatus')} valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  )
}
