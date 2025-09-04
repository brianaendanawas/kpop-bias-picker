import json
import os
import base64
import boto3
from boto3.dynamodb.conditions import Key, Attr
from datetime import datetime
from urllib.parse import unquote

TABLE_NAME = os.environ.get("TABLE_NAME", "BiasPicker")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
        },
        "body": json.dumps(body)
    }

def _parse_body(event):
    if not event.get("body"):
        return {}
    body = event["body"]
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body).decode("utf-8")
        except Exception:
            return {}
    try:
        return json.loads(body or "{}")
    except Exception:
        return {}

def _now_iso():
    return datetime.utcnow().isoformat() + "Z"

def _clean_id(s):
    return "".join(ch for ch in s.lower() if (ch.isalnum() or ch == "-"))

# ---------- data helpers (pk/sk are lowercase) ----------
def group_pk(group_id): return f"GROUP#{group_id}"
def member_sk(member_id): return f"MEMBER#{member_id}"

# ---------- routes ----------
def create_group(payload):
    group_id = _clean_id(payload.get("groupId", "").strip())
    group_name = payload.get("groupName", "").strip()
    members = payload.get("members", [])

    if not group_id or not group_name or not isinstance(members, list) or len(members) == 0:
        return _resp(400, {"message": "groupId, groupName, and non-empty members[] are required"})

    meta_key = {"pk": group_pk(group_id), "sk": "META"}
    existing = table.get_item(Key=meta_key).get("Item")
    if existing:
        return _resp(409, {"message": f"group '{group_id}' already exists"})

    now = _now_iso()
    with table.batch_writer() as batch:
        batch.put_item(Item={
            "pk": meta_key["pk"],
            "sk": meta_key["sk"],
            "groupId": group_id,
            "groupName": group_name,
            "createdAt": now
        })
        for m in members:
            member_id = _clean_id(str(m))
            if not member_id:
                continue
            batch.put_item(Item={
                "pk": meta_key["pk"],
                "sk": member_sk(member_id),
                "groupId": group_id,
                "memberId": member_id,
                "memberName": str(m),
                "votes": 0,
                "createdAt": now
            })

    return _resp(201, {"message": "group created", "groupId": group_id})

def list_groups():
    # Scan META rows only (small projects: fine)
    scan = table.scan(
        FilterExpression=Attr("sk").eq("META"),
        ProjectionExpression="groupId, groupName, createdAt"
    )
    items = scan.get("Items", [])
    items.sort(key=lambda x: x.get("groupName", "").lower())
    return _resp(200, {"groups": items})

def get_group(group_id):
    group_id = _clean_id(group_id)
    pk = group_pk(group_id)

    meta = table.get_item(Key={"pk": pk, "sk": "META"}).get("Item")
    if not meta:
        return _resp(404, {"message": "group not found"})

    res = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("MEMBER#")
    )
    members = [
        {
            "memberId": it["memberId"],
            "memberName": it.get("memberName", it["memberId"]),
            "votes": int(it.get("votes", 0))
        }
        for it in res.get("Items", [])
    ]
    # sort for stable UI (by name asc) or by votes desc; pick one—keeping by name for group view
    members.sort(key=lambda x: (x["memberName"] or "").lower())

    return _resp(200, {
        "groupId": meta["groupId"],
        "groupName": meta["groupName"],
        "members": members
    })

def vote_member(group_id, payload):
    group_id = _clean_id(group_id)
    member_id = _clean_id(payload.get("memberId", ""))

    if not member_id:
        return _resp(400, {"message": "memberId is required"})

    pk = group_pk(group_id)
    sk = member_sk(member_id)

    try:
        upd = table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="SET votes = if_not_exists(votes, :zero) + :one, lastVotedAt = :ts",
            ExpressionAttributeValues={":one": 1, ":zero": 0, ":ts": _now_iso()},
            ConditionExpression=Attr("pk").exists() & Attr("sk").exists(),
            ReturnValues="ALL_NEW"
        )
        item = upd["Attributes"]
        return _resp(200, {
            "message": "vote recorded",
            "memberId": item["memberId"],
            "memberName": item.get("memberName", item["memberId"]),
            "votes": int(item.get("votes", 0))
        })
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return _resp(404, {"message": "member or group not found"})

def get_results(group_id):
    """
    Returns both:
      - results: { memberId: votes, ... }        # compact map
      - members: [{memberId, memberName, votes}] # pretty, sorted by votes desc then name
    """
    group_id = _clean_id(group_id)
    pk = group_pk(group_id)

    # confirm group exists
    meta = table.get_item(Key={"pk": pk, "sk": "META"}).get("Item")
    if not meta:
        return _resp(404, {"message": "group not found"})

    # fetch members
    res = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("MEMBER#")
    )
    items = res.get("Items", [])

    results = { it["memberId"]: int(it.get("votes", 0)) for it in items }
    pretty = [{
        "memberId": it["memberId"],
        "memberName": it.get("memberName", it["memberId"]),
        "votes": int(it.get("votes", 0))
    } for it in items]

    pretty.sort(key=lambda x: (-x["votes"], x["memberName"].lower()))
    return _resp(200, {"groupId": group_id, "results": results, "members": pretty})

# ---------- router (keeps your 'handler' entrypoint) ----------
def handler(event, context):
    method = (event.get("requestContext", {}).get("http", {}).get("method") or
              event.get("httpMethod") or "GET").upper()
    raw_path = event.get("rawPath") or event.get("path") or "/"
    path_params = event.get("pathParameters") or {}
    body = _parse_body(event)

    # normalize (no trailing slash)
    path = raw_path.rstrip("/")

    # CORS preflight
    if method == "OPTIONS":
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
            },
            "body": ""
        }

    # GET /groups/{groupId}/results
    if path.endswith("/results") and method == "GET":
        group_id = path_params.get("groupId")
        if not group_id:
            parts = path.split("/")
            group_id = unquote(parts[2]) if len(parts) >= 4 else ""
        return get_results(group_id)

    # POST /groups
    if path == "/groups" and method == "POST":
        return create_group(body)

    # GET /groups
    if path == "/groups" and method == "GET":
        return list_groups()

    # GET /groups/{groupId}  (anything that isn't /vote or /results)
    if (path.startswith("/groups/") and method == "GET"
        and not path.endswith("/vote") and not path.endswith("/results")):
        group_id = path_params.get("groupId") or unquote(path.split("/")[2])
        return get_group(group_id)

    # POST /groups/{groupId}/vote
    if path.endswith("/vote") and method == "POST":
        group_id = path_params.get("groupId")
        if not group_id:
            parts = path.split("/")
            group_id = unquote(parts[2]) if len(parts) >= 4 else ""
        return vote_member(group_id, body)

    return _resp(404, {"message": "route not found"})
