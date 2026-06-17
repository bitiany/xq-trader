export { request, http } from '@/api/client'
export type { RequestOptions } from '@/api/client'
export { API_BASE_URL, API_SUCCESS_CODE, XQTRADER_PROXY_TARGET, AI_GATEWAY_PROXY_TARGET } from '@/api/config'
export {
  aiModelApi,
  normalizeModelList,
  normalizeProviderList,
} from '@/api/ai/models'
export {
  aiProviderApi,
  normalizeProviderKeyList,
  normalizeProviderDefinitionList,
} from '@/api/ai/providers'
export { callLogsApi } from '@/api/ai/callLogs'
export type { CallLogsStats, ModelCallStat } from '@/api/ai/callLogs'
export type {
  AiModelItem,
  AiModelListParams,
  AiModelProvider,
  AddProviderPayload,
  CreateModelPayload,
  UpdateModelPayload,
  UpdateProviderPayload,
} from '@/api/ai/models'
export type {
  AiProviderDefinition,
  AiProviderKey,
  CreateProviderKeyPayload,
  UpdateProviderKeyPayload,
} from '@/api/ai/providers'
export { agentChatApi, subscribeAgentRun } from '@/api/agent'
export type { AgentSession, AgentStreamEvent, SubmitMessageResult } from '@/api/agent'
export { ApiError, isApiError, extractPageItems } from '@/api/types'
export type { ApiResponse, ApiPageParams, ApiPageResult } from '@/api/types'
export { fetchLatestTradeDate } from '@/api/data'
export type { LatestTradeDateResponse } from '@/api/data'

export {
  fetchStrategies,
  fetchStrategyDetail,
  createStrategy,
  updateStrategy,
  deleteStrategy,
  fetchRuleGroups,
  createRuleGroup,
  updateRuleGroup,
  deleteRuleGroup,
  fetchRuleBindings,
  createRuleBinding,
  updateRuleBinding,
  deleteRuleBinding,
} from '@/api/strategy'
export type {
  Strategy,
  StrategyDetail,
  StrategyStatus,
  StrategyListParams,
  StrategyCreatePayload,
  StrategyUpdatePayload,
  RuleGroup,
  RuleGroupType,
  RuleGroupCreatePayload,
  RuleGroupUpdatePayload,
  RuleBinding,
  RuleBindingCreatePayload,
  RuleBindingUpdatePayload,
  CombinationMethod,
} from '@/api/strategy'

export {
  fetchRules,
  createRule,
  updateRule,
  fetchRuleDetail,
  fetchRuleFactors,
} from '@/api/rule'
export type {
  Rule,
  RuleCategory,
  RuleType,
  RuleStatus,
  RuleListParams,
  RuleCreatePayload,
  RuleUpdatePayload,
  RuleFactorDep,
} from '@/api/rule'

export {
  fetchFactors,
  fetchFactorCategories,
  fetchFactorDetail,
  fetchFactorValues,
  fetchFactorStats,
  fetchFactorStatsLatest,
} from '@/api/factor'
export type {
  Factor,
  FactorListParams,
  FactorCategoryStat,
  FactorValue,
  FactorStats,
  FactorDirection,
  FactorStatus,
} from '@/api/factor'

export { fetchPools, fetchPoolSymbols } from '@/api/universe'
export type { Pool, PoolType, PoolSecurity, PoolSymbolsParams } from '@/api/universe'

export {
  runSelection,
  fetchSelectionResults,
  fetchSelectionDates,
} from '@/api/selection'
export type {
  SelectionRunPayload,
  SelectionRunResponse,
  SelectionItem,
  SelectionFilterStep,
  SelectionResult,
  SelectionResultsParams,
  SelectionDatesParams,
  UniverseType,
} from '@/api/selection'
