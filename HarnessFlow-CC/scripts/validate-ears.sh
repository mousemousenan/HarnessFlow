#!/bin/sh

set -u

REQUIREMENTS_FILE="${1:-docs/harnessflow/00_REQUIREMENTS.md}"

if [ ! -f "$REQUIREMENTS_FILE" ]; then
  echo "❌ 需求书不存在: $REQUIREMENTS_FILE"
  exit 1
fi

echo "📋 校验需求书 EARS 格式: $REQUIREMENTS_FILE"

ubiquitous=$(grep -c "The system shall" "$REQUIREMENTS_FILE" || true)
event_driven=$(grep -Ec "WHEN .+, the system shall" "$REQUIREMENTS_FILE" || true)
unwanted=$(grep -Ec "IF .+, THEN the system shall" "$REQUIREMENTS_FILE" || true)
state_driven=$(grep -Ec "WHILE .+, the system shall" "$REQUIREMENTS_FILE" || true)
optional=$(grep -Ec "WHERE .+, the system shall" "$REQUIREMENTS_FILE" || true)

ears_count=$((ubiquitous + event_driven + unwanted + state_driven + optional))

if [ "$ears_count" -eq 0 ]; then
  echo "⚠️  警告: 未检测到 EARS 格式需求"
else
  echo "✅ 发现 $ears_count 条 EARS 格式需求"
  echo "   Ubiquitous: $ubiquitous"
  echo "   Event-driven: $event_driven"
  echo "   Unwanted: $unwanted"
  echo "   State-driven: $state_driven"
  echo "   Optional: $optional"
fi

req_ids=$(grep -Ec "REQ-[0-9]+" "$REQUIREMENTS_FILE" || true)
echo "✅ 发现 $req_ids 处需求 ID"

if grep -q "| 需求 ID | 验收标准 |" "$REQUIREMENTS_FILE"; then
  echo "✅ 发现验收标准表格"
else
  echo "⚠️  警告: 缺少验收标准表格"
fi

echo "✅ 校验完成（警告不阻塞既有项目）"
exit 0
