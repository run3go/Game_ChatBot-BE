class IntentRouter:

    SIMPLE_KEYWORDS = ["스킬", "보석", "각인", "아바타", "장비", "아크그리드", "아크패시브",
                       "능력치", "카드", "내실", "수집"]
    TRADING_KEYWORDS = ["가격", "시세", "거래소", "경매장", "얼마"]

    COMPLEX_KEYWORDS = ["몇", "갯수", "비교", "더", "높", "계산"]

    def route(self, question):

        if "정보" in question:
            return "COMPLEX"

        for word in self.COMPLEX_KEYWORDS:
            if word in question:
                return "COMPLEX"

        for word in self.TRADING_KEYWORDS:
            if word in question:
                return "TRADING"
            
        for word in self.SIMPLE_KEYWORDS:
            if word in question:
                return "CHARACTER"
            
        return "COMPLEX"