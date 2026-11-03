import type { TFunction } from 'i18next'
import { Hash, Mail, Send, Webhook } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { AlertChannel, AlertRule, ChannelType } from '../services/api'
import { formatRuleValue, metricLabel } from './format'

export const CHANNEL_ICON: Record<ChannelType, LucideIcon> = {
  telegram: Send,
  webhook: Webhook,
  slack: Hash,
  email: Mail,
}

export function ruleLabel(rule: AlertRule, t: TFunction): string {
  return `${metricLabel(rule.metric_name, t)} ${rule.operator} ${formatRuleValue(rule.metric_name, rule.threshold)}`
}

/** Where a channel delivers, as the API returns it (URLs and e-mails already masked). */
export function channelTarget(channel: AlertChannel, t: TFunction): string {
  const { config } = channel
  if (channel.channel_type === 'telegram') {
    return config.uses_default_chat ? `${config.chat_id} (${t('alerts.channels.defaultChat')})` : String(config.chat_id)
  }
  return String(config.url ?? config.webhook_url ?? config.to ?? '')
}
