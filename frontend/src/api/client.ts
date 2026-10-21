/**
 * Typed wrappers for every endpoint that actually exists in the backend.
 *
 * Nothing here is invented. Each function corresponds to a documented endpoint
 * in `docs/api-contract.md`, and the paths match the running FastAPI app.
 *
 * Endpoints that do NOT exist (AI inference, analytics, WebSocket alerts) are
 * deliberately absent, so the compiler prevents a page from calling them.
 */

import { request } from './http'
import type {
  ActivityEvent,
  ActivityEventCreate,
  Alert,
  AlertCreate,
  CarePlan,
  CarePlanCreate,
  CaregiverAssignment,
  Checkin,
  CheckinCreate,
  CheckinSchedule,
  ElderlyProfile,
  ElderlyProfileCreate,
  HealthResponse,
  LoginPayload,
  MedicationSchedule,
  MedicationScheduleCreate,
  MessageResponse,
  Page,
  RegisterPayload,
  Reminder,
  ReminderCreate,
  TokenResponse,
  User,
} from './types'

const V1 = '/api/v1'

export const api = {
  // -------------------------------------------------------------------------
  // System
  // -------------------------------------------------------------------------

  /** `GET /api/v1/health` — real database connectivity check. */
  health: () => request<HealthResponse>(`${V1}/health`, { authenticated: false }),

  // -------------------------------------------------------------------------
  // Authentication
  // -------------------------------------------------------------------------

  register: (payload: RegisterPayload) =>
    request<TokenResponse>(`${V1}/auth/register`, {
      method: 'POST',
      body: payload,
      authenticated: false,
    }),

  login: (payload: LoginPayload) =>
    request<TokenResponse>(`${V1}/auth/login`, {
      method: 'POST',
      body: payload,
      authenticated: false,
    }),

  me: () => request<User>(`${V1}/auth/me`),

  // -------------------------------------------------------------------------
  // Elderly profiles
  // -------------------------------------------------------------------------

  listProfiles: (params?: { page?: number; page_size?: number; include_inactive?: boolean }) =>
    request<Page<ElderlyProfile>>(`${V1}/elderly-profiles`, { query: params }),

  getProfile: (profileId: number) =>
    request<ElderlyProfile>(`${V1}/elderly-profiles/${profileId}`),

  createProfile: (payload: ElderlyProfileCreate) =>
    request<ElderlyProfile>(`${V1}/elderly-profiles`, { method: 'POST', body: payload }),

  updateProfile: (profileId: number, payload: Partial<ElderlyProfileCreate>) =>
    request<ElderlyProfile>(`${V1}/elderly-profiles/${profileId}`, {
      method: 'PATCH',
      body: payload,
    }),

  deactivateProfile: (profileId: number) =>
    request<MessageResponse>(`${V1}/elderly-profiles/${profileId}`, { method: 'DELETE' }),

  // -------------------------------------------------------------------------
  // Caregivers
  // -------------------------------------------------------------------------

  listCaregivers: (profileId: number) =>
    request<CaregiverAssignment[]>(`${V1}/elderly-profiles/${profileId}/caregivers`),

  // -------------------------------------------------------------------------
  // Care plans
  // -------------------------------------------------------------------------

  listCarePlans: (profileId: number, params?: { page?: number; page_size?: number }) =>
    request<Page<CarePlan>>(`${V1}/elderly-profiles/${profileId}/care-plans`, {
      query: params,
    }),

  createCarePlan: (profileId: number, payload: CarePlanCreate) =>
    request<CarePlan>(`${V1}/elderly-profiles/${profileId}/care-plans`, {
      method: 'POST',
      body: payload,
    }),

  updateCarePlan: (planId: number, payload: Partial<CarePlanCreate>) =>
    request<CarePlan>(`${V1}/care-plans/${planId}`, { method: 'PATCH', body: payload }),

  deleteCarePlan: (planId: number) =>
    request<MessageResponse>(`${V1}/care-plans/${planId}`, { method: 'DELETE' }),

  // -------------------------------------------------------------------------
  // Medications
  // -------------------------------------------------------------------------

  listMedications: (profileId: number, includeInactive = false) =>
    request<MedicationSchedule[]>(`${V1}/elderly-profiles/${profileId}/medications`, {
      query: { include_inactive: includeInactive },
    }),

  createMedication: (profileId: number, payload: MedicationScheduleCreate) =>
    request<MedicationSchedule>(`${V1}/elderly-profiles/${profileId}/medications`, {
      method: 'POST',
      body: payload,
    }),

  // -------------------------------------------------------------------------
  // Reminders
  // -------------------------------------------------------------------------

  listReminders: (profileId: number, includeInactive = false) =>
    request<Reminder[]>(`${V1}/elderly-profiles/${profileId}/reminders`, {
      query: { include_inactive: includeInactive },
    }),

  createReminder: (profileId: number, payload: ReminderCreate) =>
    request<Reminder>(`${V1}/elderly-profiles/${profileId}/reminders`, {
      method: 'POST',
      body: payload,
    }),

  // -------------------------------------------------------------------------
  // Check-ins
  // -------------------------------------------------------------------------

  listCheckins: (profileId: number, params?: { page?: number; page_size?: number }) =>
    request<Page<Checkin>>(`${V1}/elderly-profiles/${profileId}/checkins`, { query: params }),

  createCheckin: (profileId: number, payload: CheckinCreate) =>
    request<Checkin>(`${V1}/elderly-profiles/${profileId}/checkins`, {
      method: 'POST',
      body: payload,
    }),

  createCheckinSchedule: (
    profileId: number,
    payload: { title: string; checkin_type?: string; recurrence?: string; time_of_day?: string | null },
  ) =>
    request<CheckinSchedule>(`${V1}/elderly-profiles/${profileId}/checkin-schedules`, {
      method: 'POST',
      body: payload,
    }),

  // -------------------------------------------------------------------------
  // Activity events
  // -------------------------------------------------------------------------

  listActivityEvents: (
    profileId: number,
    params?: { page?: number; page_size?: number; start?: string; end?: string },
  ) => request<Page<ActivityEvent>>(`${V1}/elderly-profiles/${profileId}/activity-events`, {
    query: params,
  }),

  createActivityEvent: (profileId: number, payload: ActivityEventCreate) =>
    request<ActivityEvent>(`${V1}/elderly-profiles/${profileId}/activity-events`, {
      method: 'POST',
      body: payload,
    }),

  // -------------------------------------------------------------------------
  // Alerts
  // -------------------------------------------------------------------------

  listAlerts: (params?: {
    page?: number
    page_size?: number
    status?: string
    severity?: string
  }) => request<Page<Alert>>(`${V1}/alerts`, { query: params }),

  listProfileAlerts: (profileId: number, params?: { page?: number; page_size?: number }) =>
    request<Page<Alert>>(`${V1}/elderly-profiles/${profileId}/alerts`, { query: params }),

  createAlert: (profileId: number, payload: AlertCreate) =>
    request<Alert>(`${V1}/elderly-profiles/${profileId}/alerts`, {
      method: 'POST',
      body: payload,
    }),

  acknowledgeAlert: (alertId: number, note?: string) =>
    request<Alert>(`${V1}/alerts/${alertId}/acknowledge`, {
      method: 'POST',
      body: note ? { note } : {},
    }),

  updateAlertStatus: (alertId: number, status: string) =>
    request<Alert>(`${V1}/alerts/${alertId}`, { method: 'PATCH', body: { status } }),
}
