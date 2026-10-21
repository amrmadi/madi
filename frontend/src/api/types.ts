/**
 * TypeScript types mirroring the backend's Pydantic schemas.
 *
 * Why hand-written types and not "just `any`": the backend contract is the
 * source of truth (see `docs/api-contract.md`), and these types make the
 * compiler catch a misspelled field before a caregiver ever sees a broken page.
 *
 * If the backend changes a schema, update the matching type here. The file is
 * deliberately organised in the same order as the API contract.
 */

// ---------------------------------------------------------------------------
// Enums (string unions — the backend stores exactly these values)
// ---------------------------------------------------------------------------

export type UserRole = 'admin' | 'caregiver' | 'elderly' | 'analyst'
export type UserStatus = 'active' | 'invited' | 'disabled'
export type AssignmentRole = 'primary' | 'secondary' | 'emergency' | 'observer'
export type CarePlanStatus = 'draft' | 'active' | 'paused' | 'completed' | 'cancelled'
export type RecurrencePattern = 'once' | 'daily' | 'weekly' | 'monthly' | 'as_needed'
export type ScheduleStatus = 'scheduled' | 'taken' | 'missed' | 'skipped' | 'cancelled'
export type SeverityLevel = 'info' | 'low' | 'medium' | 'high' | 'critical'
export type AlertStatus = 'new' | 'acknowledged' | 'resolved' | 'dismissed'
export type AlertType =
  | 'fall'
  | 'anomaly'
  | 'risk'
  | 'missed_medication'
  | 'missed_checkin'
  | 'system'
export type CheckinType = 'manual' | 'automatic' | 'wellbeing' | 'safety'
export type ActivityType =
  | 'walking'
  | 'standing'
  | 'sitting'
  | 'lying'
  | 'eating'
  | 'sleeping'
  | 'toileting'
  | 'unknown'
export type EventSource =
  | 'simulated'
  | 'sensor'
  | 'manual_entry'
  | 'imported_dataset'
  | 'model'

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: 'ok' | 'degraded'
  database: 'connected' | 'disconnected'
  version: string
  environment: string
}

// ---------------------------------------------------------------------------
// Authentication
// ---------------------------------------------------------------------------

export interface User {
  id: number
  email: string
  display_name: string
  phone: string | null
  role: UserRole
  status: UserStatus
  is_active: boolean
  is_email_verified: boolean
  created_at: string
  last_login_at: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface RegisterPayload {
  email: string
  display_name: string
  password: string
  phone?: string | null
  role?: UserRole
}

export interface LoginPayload {
  email: string
  password: string
}

// ---------------------------------------------------------------------------
// Elderly profiles
// ---------------------------------------------------------------------------

export interface ElderlyProfile {
  id: number
  display_name: string
  date_of_birth: string | null
  room_label: string | null
  notes: string | null
  mobility_notes: string | null
  linked_user_id: number | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ElderlyProfileCreate {
  display_name: string
  date_of_birth?: string | null
  room_label?: string | null
  notes?: string | null
  mobility_notes?: string | null
}

export interface CaregiverAssignment {
  id: number
  caregiver_id: number
  elderly_profile_id: number
  assignment_role: AssignmentRole
  is_active: boolean
  assigned_at: string
  ended_at: string | null
  caregiver_display_name: string | null
  caregiver_email: string | null
}

// ---------------------------------------------------------------------------
// Care plans
// ---------------------------------------------------------------------------

export interface CarePlan {
  id: number
  elderly_profile_id: number
  created_by_user_id: number | null
  title: string
  summary: string | null
  status: CarePlanStatus
  start_date: string | null
  end_date: string | null
  created_at: string
  updated_at: string
}

export interface CarePlanCreate {
  title: string
  summary?: string | null
  status?: CarePlanStatus
  start_date?: string | null
  end_date?: string | null
}

// ---------------------------------------------------------------------------
// Medications
// ---------------------------------------------------------------------------

export interface MedicationSchedule {
  id: number
  elderly_profile_id: number
  medication_name: string
  dosage_text: string | null
  instructions: string | null
  recurrence: RecurrencePattern
  time_of_day: string | null
  start_date: string | null
  end_date: string | null
  is_active: boolean
  created_at: string
}

export interface MedicationScheduleCreate {
  medication_name: string
  dosage_text?: string | null
  instructions?: string | null
  recurrence?: RecurrencePattern
  time_of_day?: string | null
  is_active?: boolean
}

// ---------------------------------------------------------------------------
// Reminders
// ---------------------------------------------------------------------------

export interface Reminder {
  id: number
  elderly_profile_id: number
  title: string
  message: string | null
  recurrence: RecurrencePattern
  time_of_day: string | null
  day_of_week: number | null
  is_active: boolean
  created_at: string
}

export interface ReminderCreate {
  title: string
  message?: string | null
  recurrence?: RecurrencePattern
  time_of_day?: string | null
  day_of_week?: number | null
  is_active?: boolean
}

// ---------------------------------------------------------------------------
// Check-ins
// ---------------------------------------------------------------------------

export interface Checkin {
  id: number
  elderly_profile_id: number
  checkin_schedule_id: number | null
  checkin_type: CheckinType
  status: ScheduleStatus
  scheduled_for: string | null
  performed_at: string | null
  wellbeing_note: string | null
  recorded_by_user_id: number | null
  created_at: string
}

export interface CheckinCreate {
  checkin_type?: CheckinType
  status?: ScheduleStatus
  scheduled_for?: string | null
  performed_at?: string | null
  wellbeing_note?: string | null
  checkin_schedule_id?: number | null
}

export interface CheckinSchedule {
  id: number
  elderly_profile_id: number
  title: string
  checkin_type: CheckinType
  recurrence: RecurrencePattern
  time_of_day: string | null
  is_active: boolean
  created_at: string
}

// ---------------------------------------------------------------------------
// Activity events
// ---------------------------------------------------------------------------

export interface ActivityEvent {
  id: number
  elderly_profile_id: number
  model_run_id: number | null
  activity_type: ActivityType
  confidence: number | null
  started_at: string
  ended_at: string | null
  duration_seconds: number | null
  /** Defaults to "simulated" on the server — never present demo data as real. */
  source: EventSource
  room_label: string | null
  note: string | null
  created_at: string
}

export interface ActivityEventCreate {
  activity_type: ActivityType
  confidence?: number | null
  started_at: string
  ended_at?: string | null
  duration_seconds?: number | null
  room_label?: string | null
  note?: string | null
  source?: EventSource
}

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------

export interface Alert {
  id: number
  elderly_profile_id: number
  alert_type: AlertType
  severity: SeverityLevel
  status: AlertStatus
  title: string
  message: string | null
  source_event_type: string | null
  source_event_id: number | null
  occurrence_count: number
  created_at: string
  acknowledged_at: string | null
  acknowledged_by_user_id: number | null
  resolved_at: string | null
  elderly_profile_name: string | null
}

export interface AlertCreate {
  alert_type: AlertType
  severity?: SeverityLevel
  title: string
  message?: string | null
}

// ---------------------------------------------------------------------------
// Shared response shapes
// ---------------------------------------------------------------------------

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** The shape of every error the API returns (see the contract's error envelope). */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details: ApiErrorDetails | null
  }
}

export interface ApiErrorDetails {
  fields?: Array<{ field: string; message: string; type: string }>
  [key: string]: unknown
}

export interface MessageResponse {
  detail: string
}
