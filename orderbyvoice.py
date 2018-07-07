# -*- coding: utf-8 -*-

from __future__ import print_function
import datetime
from flask import Flask
app = Flask(__name__)

from flask import redirect, request, render_template, url_for, make_response
import json, os
import redis
import uuid

if os.environ.get('redis_host'):
    r = redis.StrictRedis(host=os.environ.get('redis_host'), port=6379, db=0)
else:
    r = redis.StrictRedis(host='localhost', port=6379, db=0)
# DDSのJSON保存ファイルを使ってメニューを言えるようにする
menu_json = json.loads(open("order.json", "r").read()).get("children")
menu = []
for item in menu_json:
    menu.append(item["value"])


# ------------ Webサービスの処理
@app.route('/')
def main():
    orders = r.lrange("order", 0, 100)
    orders_web = []
    total = []
    for item_v in menu:
        total.append(0)

    for order_json in orders:
        order = json.loads(order_json)
        orders_item = []
        orders_item.append(order["timestamp"])
        orders_item.append(order["user_id"])
        orders_item.append("Room 101A")
        i = 0
        item = order["drinkorder"]
        print(item)
        for item_v in menu:
            if item.get(item_v):
                orders_item.append(str(item.get(item_v)))
                total[i] += int(item.get(item_v))
            else:
                orders_item.append(str(0))
            i += 1

        orders_web.append({"item": orders_item, "link": order["orderID"]})

    return render_template(
        'main.html',
        menu=menu,
        orders=orders_web,
        total=total)


# オーダーの削除
@app.route('/ordercomplete')
def ordercomplete():
    if request.args.get('orderid'):
        orderid = request.args.get('orderid')
        orders = r.lrange("order", 0, 100)
        for order_json in orders:
            order = json.loads(order_json)
            if order["orderID"] == orderid:
                r.lrem("order", 0, order_json)
    return redirect(url_for('main'))


# オーダーの変化検出用
@app.route('/orderlist')
def orderlist():
    number = r.llen("order")
    return json.dumps(number)


# ---------------- ここからは音声処理
# エンドポイントの受付処理
@app.route('/order', methods=['GET', 'POST'])
def order():
    if request.method == 'POST' and 'application/json' in request.headers.get('Content-Type', ""):
        event = request.json
        response = make_response()
        response.status_code = 200
        response.data = event_handler(event, "")
        print(response.data)
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
    else:
        return "Error"


# Redisへの書き込み
def put_drink_order(user_id, drinkorder, confirm, ittr):
    r.set(user_id, json.dumps({
        "drinkorder": drinkorder,
        "confirm": confirm,
        "ittr": ittr
    }))


# テキスト処理
def txt_in_txt(list, target, mark):
    result = None
    for txt in list:
        if txt in target:
            result = mark
    return result


# イベントハンドラ
def event_handler(event, context):
    print(json.dumps(event, ensure_ascii=False, indent=2, encoding='utf-8'))

    intent = event["args"]["intent"]
    utterance = event["args"]["utterance"]
    user_id = event["user_id"]

    # エンドポイントテスト用
    if user_id == "test":
        return respond(
            None,
            {"error_code": "success",
             "status": "true",
             "user_id": event["user_id"],
             "bot_id": event["bot_id"],
             "params": {"status": "true",
                        "message": "",
                        }
             }
        )

    # Redisからデータ収集
    if r.get(user_id):
        items = json.loads(r.get(user_id))
    else:
        items = {}

    drinkorder = {}
    sentense = ""
    system_utterance = ""
    confirm = 0
    ittr = 0
    talkend = "false"

    # この時点でのオーダーの解析
    if items.get('drinkorder'):
        drinkorder = items.get('drinkorder')
        if drinkorder is None:
            drinkorder = {}
        confirm = items.get('confirm')
        ittr = items.get('ittr')
        if ittr is None:
            ittr = 0

    # Sebastienからのオーダーの受け取り
    items = {}
    if intent == "init":
        # オーダー初期化
        put_drink_order(user_id, {}, 0, 0)

    # メニュー確認
    elif intent == "menu":
        sentense = u"ご用意できるのは、" + u"、".join(menu) + u"です。ご注文をどうぞ。"
        system_utterance = u"ご用意できるのは、" + u"、".join(menu) + u"です。ご注文をどうぞ。"

    # ドリンクオーダの解析
    elif intent == "order":
        sentense = u""
        drinks = event["args"].get('drink')
        numbers = event["args"].get('number')
        if len(drinks) == len(numbers):
            for drinkset in zip(drinks, numbers):
                sentense += drinkset[0] + u"を" + drinkset[1] + u"個、"
                drinkorder[drinkset[0]] = drinkset[1]
            sentense += u"承りました。以上でよろしいですか？"
        elif len(numbers) == 1:
            for drinkset in drinks:
                sentense += drinkset + u"を" + numbers[0] + u"個、"
                drinkorder[drinkset] = numbers[0]
            sentense += u"承りました。以上でよろしいですか？"
        else:
            sentense = u"オーダーが複雑すぎて理解できませんでした。申し訳ありません。一つずつお願いします。"

        ittr += 1
        put_drink_order(user_id, drinkorder, 0, ittr)

    else:
        # オーダー間違い
        if u"違" in utterance or u"いいえ" in utterance or u"あってません" in utterance or u"あってない" in utterance:
            sentense = u"ご注文内容を最初からもう一度お願いします。"
            put_drink_order(user_id, {}, 0, ittr)

        # オーダー完了
        elif (u"以上" in utterance or u"願" in utterance or u"はい" in utterance or u"あってます" in utterance) and (confirm == 1 or ittr == 1):
            current_order_number = r.llen("order") + 1
            sentense = u"ご注文を承りました。" + str(current_order_number * 3) + u"分でお届けします。では失礼します。"
            talkend = "true"
            r.rpush("order", json.dumps({
                "user_id": user_id,
                "orderID": str(uuid.uuid4()),
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "drinkorder": drinkorder
            }))
            put_drink_order(user_id, {}, 0, ittr)

        # オーダー再確認
        elif (u"以上" in utterance or u"はい" in utterance or u"願" in utterance) and confirm == 0:
            orders = []
            for order in drinkorder.keys():
                orders.append(order + u"を" + drinkorder[order] + u"個")
            sentense = u"ご注文を繰り返します。" + u"、".join(orders) + u"ですね。よろしいでしょうか？"
            put_drink_order(user_id, drinkorder, 1, ittr)

        else:
            sentense = u"ご注文をどうぞ"

    if system_utterance == "":
        system_utterance = sentense

    return respond(
        None,
        {"error_code": "success",
         "status": "true",
         "user_id": event["user_id"],
         "bot_id": event["bot_id"],
         "params": {"status": "true",
                    "message": sentense,
                    "option": {
                        "readText": system_utterance
                    },
                    "talkend": talkend,
                    }
         }
    )


def respond(err, res=None):
    return json.dumps(res)


if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True, port=5123)
