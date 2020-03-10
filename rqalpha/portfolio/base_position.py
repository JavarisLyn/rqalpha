# -*- coding: utf-8 -*-
# 版权所有 2019 深圳米筐科技有限公司（下称“米筐科技”）
#
# 除非遵守当前许可，否则不得使用本软件。
#
#     * 非商业用途（非商业用途指个人出于非商业目的使用本软件，或者高校、研究所等非营利机构出于教育、科研等目的使用本软件）：
#         遵守 Apache License 2.0（下称“Apache 2.0 许可”），
#         您可以在以下位置获得 Apache 2.0 许可的副本：http://www.apache.org/licenses/LICENSE-2.0。
#         除非法律有要求或以书面形式达成协议，否则本软件分发时需保持当前许可“原样”不变，且不得附加任何条件。
#
#     * 商业用途（商业用途指个人出于任何商业目的使用本软件，或者法人或其他组织出于任何目的使用本软件）：
#         未经米筐科技授权，任何个人不得出于任何商业目的使用本软件（包括但不限于向第三方提供、销售、出租、出借、转让本软件、
#         本软件的衍生产品、引用或借鉴了本软件功能或源代码的产品或服务），任何法人或其他组织不得出于任何目的使用本软件，
#         否则米筐科技有权追究相应的知识产权侵权责任。
#         在此前提下，对本软件的使用同样需要遵守 Apache 2.0 许可，Apache 2.0 许可与本许可冲突之处，以本许可为准。
#         详细的授权流程，请联系 public@ricequant.com 获取。

from typing import Iterable, Tuple, Optional, Dict, Type
from datetime import date
from collections import UserDict

import six

from rqalpha.interface import AbstractPosition
from rqalpha.environment import Environment
from rqalpha.const import POSITION_EFFECT, POSITION_DIRECTION, INSTRUMENT_TYPE
from rqalpha.model.order import Order
from rqalpha.model.trade import Trade
from rqalpha.model.instrument import Instrument
from rqalpha.utils.i18n import gettext as _
from rqalpha.utils.repr import property_repr, PropertyReprMeta
from rqalpha.utils import is_valid_price


class BasePosition(AbstractPosition, metaclass=PropertyReprMeta):

    __repr_properties__ = (
        "order_book_id", "direction", "quantity", "market_value", "trading_pnl", "position_pnl"
    )

    def __init__(self, order_book_id, direction, init_quantity=0):
        self._order_book_id = order_book_id
        self._instrument = Environment.get_instance().data_proxy.instruments(order_book_id)  # type: Instrument
        self._direction = direction

        self._old_quantity = init_quantity
        self._logical_old_quantity = 0
        self._today_quantity = 0

        self._avg_price = 0
        self._trade_cost = 0
        self._transaction_cost = 0

        self._non_closable = 0

        self._prev_close = None

        self._market_tplus_ = None

        self._last_price = float("NaN")

        self._direction_factor = 1 if direction == POSITION_DIRECTION.LONG else -1

    order_book_id = property(lambda self: self._order_book_id)
    direction = property(lambda self: self._direction)
    quantity = property(lambda self: self._old_quantity + self._today_quantity)
    transaction_cost = property(lambda self: self._transaction_cost)
    avg_price = property(lambda self: self._avg_price)

    @property
    def trading_pnl(self):
        raise NotImplementedError

    @property
    def position_pnl(self):
        raise NotImplementedError

    @property
    def market_value(self):
        raise NotImplementedError

    @property
    def margin(self):
        raise NotImplementedError

    @property
    def equity(self):
        # type: () -> float
        raise NotImplementedError

    @property
    def prev_close(self):
        if not is_valid_price(self._prev_close):
            env = Environment.get_instance()
            self._prev_close = env.data_proxy.get_prev_close(self._order_book_id, env.trading_dt)
        return self._prev_close

    @property
    def last_price(self):
        if self._last_price != self._last_price:
            env = Environment.get_instance()
            self._last_price = env.data_proxy.get_last_price(self._order_book_id)
            if self._last_price != self._last_price:
                raise RuntimeError(_("last price of position {} is not supposed to be nan").format(self._order_book_id))
        return self._last_price

    @property
    def closable(self):
        order_quantity = sum(o for o in self._open_orders if o.position_effect in (
            POSITION_EFFECT.CLOSE, POSITION_EFFECT.CLOSE_TODAY, POSITION_EFFECT.EXERCISE
        ))
        return self.quantity - order_quantity

    @property
    def today_closable(self):
        return self._today_quantity - sum(
            o.unfilled_quantity for o in self._open_orders if o.position_effect == POSITION_EFFECT.CLOSE_TODAY
        )

    @property
    def receivable(self):
        return 0.

    @property
    def position_validator_enabled(self):
        return True

    def get_state(self):
        return {
            "old_quantity": self._old_quantity,
            "logical_old_quantity": self._logical_old_quantity,
            "today_quantity": self._today_quantity,
            "avg_price": self._avg_price,
            "trade_cost": self._trade_cost,
            "transaction_cost": self._transaction_cost,
            "non_closable": self._non_closable,
            "prev_close": self._prev_close
        }

    def set_state(self, state):
        self._old_quantity = state.get("old_quantity", 0)
        self._logical_old_quantity = state.get("logical_old_quantity", self._old_quantity)
        self._today_quantity = state.get("today_quantity", 0)
        self._avg_price = state.get("avg_price", 0)
        self._trade_cost = state.get("trade_cost", 0)
        self._transaction_cost = state.get("transaction_cost", 0)
        self._non_closable = state.get("non_closable", 0)
        self._prev_close = state.get("prev_close")

    def before_trading(self, trading_date):
        # type: (date) -> float
        # 返回该阶段导致总资金的变化量
        raise NotImplementedError

    def settlement(self, trading_date):
        # type: (date) -> Tuple[float, Optional[Trade]]
        # 返回该阶段导致总资金的变化量以及反映该阶段引起其他持仓变化的虚拟交易，虚拟交易用于换代码，转股等操作
        raise NotImplementedError

    def apply_trade(self, trade):
        # type: (Trade) -> float
        # 返回总资金的变化量
        raise NotImplementedError

    def update_last_price(self, price):
        self._last_price = price

    def calc_close_today_amount(self, trade_amount):
        raise NotImplementedError

    @property
    def _open_orders(self):
        # type: () -> Iterable[Order]
        for order in Environment.get_instance().broker.get_open_orders(self.order_book_id):
            if order.position_direction == self._direction:
                yield order


class PositionProxy(object):
    __abandon_properties__ = [
        "positions",
        "long",
        "short"
    ]

    def __init__(self, long, short):
        # type: (BasePosition, BasePosition) -> PositionProxy
        self._long = long
        self._short = short

    __repr__ = property_repr

    @property
    def type(self):
        raise NotImplementedError

    @property
    def order_book_id(self):
        return self._long.order_book_id

    @property
    def last_price(self):
        return self._long.last_price

    @property
    def market_value(self):
        return self._long.market_value - self._short.market_value

    # -- PNL 相关
    @property
    def position_pnl(self):
        """
        [float] 昨仓盈亏，当前交易日盈亏中来源于昨仓的部分

        多方向昨仓盈亏 = 昨日收盘时的持仓 * 合约乘数 * (最新价 - 昨收价)
        空方向昨仓盈亏 = 昨日收盘时的持仓 * 合约乘数 * (昨收价 - 最新价)

        """
        return self._long.position_pnl + self._short.position_pnl

    @property
    def trading_pnl(self):
        """
        [float] 交易盈亏，当前交易日盈亏中来源于当日成交的部分

        单比买方向成交的交易盈亏 = 成交量 * (最新价 - 成交价)
        单比卖方向成交的交易盈亏 = 成交量 * (成交价 - 最新价)

        """
        return self._long.trading_pnl + self._short.trading_pnl

    @property
    def daily_pnl(self):
        """
        [float] 当日盈亏

        当日盈亏 = 昨仓盈亏 + 交易盈亏

        """
        return self._long.position_pnl + self._long.trading_pnl + self._short.position_pnl +\
               self._short.trading_pnl - self.transaction_cost

    # -- Quantity 相关
    @property
    def open_orders(self):
        return Environment.get_instance().broker.get_open_orders(self.order_book_id)

    # -- Margin 相关
    @property
    def margin(self):
        """
        [float] 保证金

        保证金 = 持仓量 * 最新价 * 合约乘数 * 保证金率

        股票保证金 = 市值 = 持仓量 * 最新价

        """
        return self._long.margin + self._short.margin

    @property
    def transaction_cost(self):
        """
        [float] 交易费率
        """
        return self._long.transaction_cost + self._short.transaction_cost

    @property
    def positions(self):
        return [self._long, self._short]

    @property
    def long(self):
        return self._long

    @property
    def short(self):
        return self._short


PositionType = Type[BasePosition]
PositionProxyType = Type[PositionProxy]
PositionDictType = Dict[str, Dict[POSITION_DIRECTION, BasePosition]]


class PositionProxyDict(UserDict):
    _position_proxy_types = {}  # type: Dict[INSTRUMENT_TYPE, PositionProxyType]

    def __init__(self, positions, position_types):
        super(PositionProxyDict, self).__init__()
        self._positions = positions  # type: PositionDictType
        self._position_types = position_types  # type: Dict[INSTRUMENT_TYPE, PositionType]

    @classmethod
    def register_position_proxy_dict(cls, instrument_type, position_proxy_type):
        # type: (INSTRUMENT_TYPE, Type[PositionProxy]) -> None
        cls._position_proxy_types[instrument_type] = position_proxy_type

    def keys(self):
        return self._positions.keys()

    def __getitem__(self, order_book_id):
        position_type, position_proxy_type = self._get_position_types(order_book_id)
        if order_book_id not in self._positions:
            long = position_type(order_book_id, POSITION_DIRECTION.LONG)
            short = position_type(order_book_id, POSITION_DIRECTION.SHORT)
        else:
            positions = self._positions[order_book_id]
            long = positions[POSITION_DIRECTION.LONG]
            short = positions[POSITION_DIRECTION.SHORT]
        return position_proxy_type(long, short)

    def __contains__(self, item):
        return item in self._positions

    def __iter__(self):
        return iter(self._positions)

    def __len__(self):
        return len(self._positions)

    def __setitem__(self, key, value):
        raise TypeError("{} object does not support item assignment".format(self.__class__.__name__))

    def __delitem__(self, key):
        raise TypeError("{} object does not support item deletion".format(self.__class__.__name__))

    def __repr__(self):
        return repr({k: self[k] for k in self._positions.keys()})

    def _get_position_types(self, order_book_id):
        # type: (str) -> Tuple[Type[BasePosition], Type[PositionProxy]]
        instrument_type = Environment.get_instance().data_proxy.instruments(order_book_id).type
        position_type = self._position_types.get(instrument_type, BasePosition)
        position_proxy_type = self._position_proxy_types.get(instrument_type, PositionProxy)
        return position_type, position_proxy_type
