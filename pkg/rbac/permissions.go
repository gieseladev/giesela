package rbac

type Permission uint

// TODO use more descriptive permission ids

const (
	_ = iota

	QueueModify Permission = iota
)
