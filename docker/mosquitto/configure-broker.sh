#!/bin/sh
set -eu

require_identity() {
    variable_name="$1"
    value="$2"
    case "$value" in
        "" | *[!A-Za-z0-9._-]*)
            echo "$variable_name must contain only letters, digits, dots, underscores, or hyphens" >&2
            exit 1
            ;;
    esac
}

require_topic_segment() {
    variable_name="$1"
    value="$2"
    case "$value" in
        "" | *[!a-z0-9-]*)
            echo "$variable_name must be a lowercase topic segment" >&2
            exit 1
            ;;
    esac
}

: "${SIMULATOR_MQTT_PASSWORD:?SIMULATOR_MQTT_PASSWORD is required}"
: "${CONSUMER_MQTT_PASSWORD:?CONSUMER_MQTT_PASSWORD is required}"
require_identity SIMULATOR_MQTT_USERNAME "${SIMULATOR_MQTT_USERNAME:-}"
require_identity CONSUMER_MQTT_USERNAME "${CONSUMER_MQTT_USERNAME:-}"
require_topic_segment FACTORY_AREA "${FACTORY_AREA:-}"
require_topic_segment MACHINE_ID "${MACHINE_ID:-}"
if [ "$SIMULATOR_MQTT_USERNAME" = "$CONSUMER_MQTT_USERNAME" ]; then
    echo "simulator and consumer MQTT usernames must be different" >&2
    exit 1
fi

auth_directory=/mosquitto/config-generated
password_file="$auth_directory/passwords"
acl_file="$auth_directory/acl"
password_temporary="$auth_directory/.passwords.tmp"
acl_temporary="$auth_directory/.acl.tmp"

mkdir -p "$auth_directory"
umask 077
mosquitto_passwd -b -c "$password_temporary" \
    "$SIMULATOR_MQTT_USERNAME" "$SIMULATOR_MQTT_PASSWORD"
mosquitto_passwd -b "$password_temporary" \
    "$CONSUMER_MQTT_USERNAME" "$CONSUMER_MQTT_PASSWORD"

{
    printf 'user %s\n' "$SIMULATOR_MQTT_USERNAME"
    printf 'topic write factory/%s/%s/telemetry\n\n' "$FACTORY_AREA" "$MACHINE_ID"
    printf 'user %s\n' "$CONSUMER_MQTT_USERNAME"
    printf 'topic read factory/+/+/telemetry\n'
    printf 'topic read $SYS/broker/version\n'
} >"$acl_temporary"

chown mosquitto:mosquitto "$password_temporary" "$acl_temporary"
mv "$password_temporary" "$password_file"
mv "$acl_temporary" "$acl_file"
exec /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
