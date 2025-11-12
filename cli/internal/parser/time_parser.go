package parser

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// ParseTime converts natural language or ISO 8601 timestamps to ISO 8601 format
func ParseTime(input string) (string, error) {
	input = strings.TrimSpace(strings.ToLower(input))
	
	// Try parsing as ISO 8601 first
	formats := []string{
		time.RFC3339,
		"2006-01-02T15:04:05Z",
		"2006-01-02 15:04:05",
		"2006-01-02 15:04",
		"2006-01-02T15:04",
	}
	
	for _, format := range formats {
		if t, err := time.Parse(format, input); err == nil {
			return t.UTC().Format(time.RFC3339), nil
		}
	}
	
	now := time.Now().UTC()
	
	// "in X minutes/hours/days"
	if strings.HasPrefix(input, "in ") {
		return parseRelativeTime(input, now)
	}
	
	// "tomorrow at HH:MM"
	if strings.HasPrefix(input, "tomorrow") {
		return parseTomorrow(input, now)
	}
	
	// "next monday/tuesday/etc at HH:MM"
	if strings.HasPrefix(input, "next ") {
		return parseNextDay(input, now)
	}
	
	// "now"
	if input == "now" {
		return now.Format(time.RFC3339), nil
	}
	
	return "", fmt.Errorf("unable to parse time: %s\n\nSupported formats:\n  - ISO 8601: 2025-11-12T19:30:00Z\n  - Relative: in 5 minutes, in 2 hours, in 3 days\n  - Tomorrow: tomorrow at 9am, tomorrow at 14:30\n  - Next day: next monday at 3pm, next friday at 10:00\n  - Now: now", input)
}

func parseRelativeTime(input string, now time.Time) (string, error) {
	// "in 5 minutes", "in 2 hours", "in 3 days"
	re := regexp.MustCompile(`^in (\d+)\s*(minute|minutes|min|hour|hours|hr|hrs|h|day|days|d)s?$`)
	matches := re.FindStringSubmatch(input)
	
	if len(matches) != 3 {
		return "", fmt.Errorf("invalid relative time format: %s", input)
	}
	
	value, _ := strconv.Atoi(matches[1])
	unit := matches[2]
	
	var t time.Time
	switch {
	case strings.HasPrefix(unit, "min"):
		t = now.Add(time.Duration(value) * time.Minute)
	case strings.HasPrefix(unit, "h"):
		t = now.Add(time.Duration(value) * time.Hour)
	case strings.HasPrefix(unit, "d"):
		t = now.AddDate(0, 0, value)
	default:
		return "", fmt.Errorf("unknown time unit: %s", unit)
	}
	
	return t.Format(time.RFC3339), nil
}

func parseTomorrow(input string, now time.Time) (string, error) {
	// "tomorrow" or "tomorrow at 9am" or "tomorrow at 14:30"
	tomorrow := now.AddDate(0, 0, 1)
	
	if input == "tomorrow" {
		// Default to 9am tomorrow
		tomorrow = time.Date(tomorrow.Year(), tomorrow.Month(), tomorrow.Day(), 9, 0, 0, 0, time.UTC)
		return tomorrow.Format(time.RFC3339), nil
	}
	
	// Parse "tomorrow at HH:MM" or "tomorrow at 9am"
	atIndex := strings.Index(input, " at ")
	if atIndex == -1 {
		return "", fmt.Errorf("expected 'at' in: %s", input)
	}
	
	timeStr := strings.TrimSpace(input[atIndex+4:])
	hour, minute, err := parseTimeOfDay(timeStr)
	if err != nil {
		return "", err
	}
	
	t := time.Date(tomorrow.Year(), tomorrow.Month(), tomorrow.Day(), hour, minute, 0, 0, time.UTC)
	return t.Format(time.RFC3339), nil
}

func parseNextDay(input string, now time.Time) (string, error) {
	// "next monday at 3pm", "next friday at 10:00"
	re := regexp.MustCompile(`^next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+at\s+(.+)$`)
	matches := re.FindStringSubmatch(input)
	
	if len(matches) != 3 {
		return "", fmt.Errorf("expected format 'next DAY at TIME': %s", input)
	}
	
	dayName := matches[1]
	timeStr := matches[2]
	
	// Find target weekday
	targetWeekday := parseWeekday(dayName)
	currentWeekday := now.Weekday()
	
	daysUntil := int(targetWeekday - currentWeekday)
	if daysUntil <= 0 {
		daysUntil += 7
	}
	
	targetDate := now.AddDate(0, 0, daysUntil)
	
	hour, minute, err := parseTimeOfDay(timeStr)
	if err != nil {
		return "", err
	}
	
	t := time.Date(targetDate.Year(), targetDate.Month(), targetDate.Day(), hour, minute, 0, 0, time.UTC)
	return t.Format(time.RFC3339), nil
}

func parseTimeOfDay(input string) (hour int, minute int, err error) {
	input = strings.TrimSpace(strings.ToLower(input))
	
	// Handle special cases
	switch input {
	case "noon", "12pm":
		return 12, 0, nil
	case "midnight", "12am":
		return 0, 0, nil
	}
	
	// Parse "3pm", "9am"
	re := regexp.MustCompile(`^(\d+)(am|pm)$`)
	matches := re.FindStringSubmatch(input)
	if len(matches) == 3 {
		h, _ := strconv.Atoi(matches[1])
		if matches[2] == "pm" && h != 12 {
			h += 12
		}
		if matches[2] == "am" && h == 12 {
			h = 0
		}
		return h, 0, nil
	}
	
	// Parse "14:30", "9:15"
	re = regexp.MustCompile(`^(\d+):(\d+)$`)
	matches = re.FindStringSubmatch(input)
	if len(matches) == 3 {
		h, _ := strconv.Atoi(matches[1])
		m, _ := strconv.Atoi(matches[2])
		if h > 23 || m > 59 {
			return 0, 0, fmt.Errorf("invalid time: %s", input)
		}
		return h, m, nil
	}
	
	return 0, 0, fmt.Errorf("unable to parse time of day: %s", input)
}

func parseWeekday(day string) time.Weekday {
	switch strings.ToLower(day) {
	case "sunday":
		return time.Sunday
	case "monday":
		return time.Monday
	case "tuesday":
		return time.Tuesday
	case "wednesday":
		return time.Wednesday
	case "thursday":
		return time.Thursday
	case "friday":
		return time.Friday
	case "saturday":
		return time.Saturday
	default:
		return time.Monday
	}
}
