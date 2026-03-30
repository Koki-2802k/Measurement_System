# ============================================================================
# ボート計測システム エントリーポイント
#
# 概要:
#   Movella DOT 3台同期計測 + GPS並行取得 + リアルタイムストローク分割の
#   一連の処理をまとめて実行する．
#
# 使い方:
#   1. 各センサにMovella DOTアプリでタグ名（boat, oar_left, oar_right）を設定
#   2. python main.py
#   3. 計測を終了するときは Ctrl+C を押す
# ============================================================================

from movelladot_pc_sdk_save_csv import run


if __name__ == "__main__":
    print("=" * 60)
    print("[SYSTEM] ボート計測システムを起動します...")
    print("=" * 60)
    try:
        run()
    except Exception as e:
        print(f"\n[エラー] システム実行中に異常が発生しました: {e}")
    finally:
        print("=" * 60)
        print("[SYSTEM] システムを終了しました．")
        print("=" * 60)
