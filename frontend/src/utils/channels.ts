import type { TFunction } from 'i18next'
import { Hash, Mail, Send, Webhook } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { AlertChannel, ChannelType } from '../services/api'

export const CHANNEL_ICON: Record<ChannelType, LucideIcon> = {
  telegram: Send,
  webhook: Webhook,
  slack: Hash,
  email: Mail,
}

/** Where a channel delivers, as the API returns it (URLs and e-mails already masked). */
export function channelTarget(channel: Pick<AlertChannel, 'channel_type' | 'config'>, t: TFunction): string {
  const { config } = channel
  if (channel.channel_type === 'telegram') {
    return config.uses_default_chat ? `${config.chat_id} (${t('alerts.channels.defaultChat')})` : String(config.chat_id)
  }
  return String(config.url ?? config.webhook_url ?? config.to ?? '')
}

/** The config field each type asks for, and whether it may stay empty. */
export const CONFIG_FIELD: Record<ChannelType, { key: string; label: string; input: 'text' | 'url' | 'email'; optional: boolean }> = {
  telegram: { key: 'chat_id', label: 'alerts.channels.field.chatId', input: 'text', optional: true },
  webhook: { key: 'url', label: 'alerts.channels.field.url', input: 'url', optional: false },
  slack: { key: 'webhook_url', label: 'alerts.channels.field.slackUrl', input: 'url', optional: false },
  email: { key: 'to', label: 'alerts.channels.field.email', input: 'email', optional: false },
}
