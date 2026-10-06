using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using QuantConnect.Brokerages;
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Securities;
using QuantConnect.Securities.Option;

namespace QuantConnect.Algorithm.CSharp
{
    /// <summary>
    /// Frozen synthetic lifecycle experiment for pinned LEAN source. The engine
    /// owns fills, buying power, automatic exercise/assignment and accounting.
    /// Zero fees are the only security-model override.
    /// </summary>
    public class ResearchDeskOptionsAlgorithm : QCAlgorithm
    {
        private const string LeanCommit = "705b9551be1aaa821c7f77896a7eb8fcd07b92ee";
        private static readonly DateTime Expiry = new DateTime(2026, 1, 16);
        private readonly object _receiptLock = new object();
        private readonly Dictionary<string, Security> _instruments = new Dictionary<string, Security>();
        private readonly Dictionary<string, object> _lastObservedTicks = new Dictionary<string, object>();
        private readonly Dictionary<string, object> _lastObservedQuoteBars = new Dictionary<string, object>();
        private readonly List<object> _slices = new List<object>();
        private readonly List<object> _orderEvents = new List<object>();
        private readonly List<object> _assignmentEvents = new List<object>();
        private readonly List<object> _submissions = new List<object>();
        private readonly List<object> _cancelRequests = new List<object>();
        private string _scenario;
        private string _receiptPath;
        private AccountType _accountType;
        private decimal _startingCash;
        private Security _underlying;
        private Option _call100;
        private Option _call120;
        private bool _entrySubmitted;
        private bool _cancelRequested;
        private bool _ended;
        private bool UsesMinuteQuotes => _scenario == "minute_itm" || _scenario == "minute_otm";

        public override void Initialize()
        {
            _scenario = GetParameter("scenario");
            _receiptPath = GetParameter("receipt-path");
            var scenarios = new[] { "native_itm", "market_itm", "market_otm", "market_shortfall",
                "market_quote_only", "market_stale_trade", "vertical_assignment", "minute_itm", "minute_otm" };
            if (!scenarios.Contains(_scenario) || string.IsNullOrWhiteSpace(_receiptPath))
            {
                throw new ArgumentException("Require a known scenario and an explicit receipt-path parameter.");
            }

            SetTimeZone(TimeZones.NewYork);
            SetStartDate(2026, 1, 15);
            SetEndDate(2026, 1, 20);
            _accountType = _scenario == "vertical_assignment" ? AccountType.Margin : AccountType.Cash;
            _startingCash = _scenario == "market_shortfall" ? 10000m : 20000m;
            SetBrokerageModel(BrokerageName.Default, _accountType);
            SetCash(_startingCash);
            AddSecurityInitializer(security => security.SetFeeModel(new ConstantFeeModel(0m)));

            // Keep the tape's underlying ticks at 16:00 and 16:00:01. Option
            // subscriptions retain their normal exchange-hours filtering.
            _underlying = AddEquity("TEST", Resolution.Tick, Market.USA, fillForward: false,
                extendedMarketHours: true, dataNormalizationMode: DataNormalizationMode.Raw);
            _instruments.Add("underlying", _underlying);
            _call100 = AddCall(100m);
            _instruments.Add("call100", _call100);
            if (_scenario == "vertical_assignment")
            {
                _call120 = AddCall(120m);
                _instruments.Add("call120", _call120);
            }
            SetBenchmark(_underlying.Symbol);
            WriteReceipt();
        }

        private Option AddCall(decimal strike)
        {
            var symbol = QuantConnect.Symbol.CreateOption(_underlying.Symbol, Market.USA,
                OptionStyle.American, OptionRight.Call, strike, Expiry);
            return AddOptionContract(symbol, UsesMinuteQuotes ? Resolution.Minute : Resolution.Tick, fillForward: false,
                extendedMarketHours: false);
        }

        public override void OnData(Slice slice)
        {
            var ticks = new List<object>();
            var quoteBars = new List<object>();
            lock (_receiptLock)
            {
                foreach (var entry in slice.Ticks.OrderBy(entry => entry.Key.ID.ToString()))
                {
                    foreach (var tick in entry.Value)
                    {
                        var record = TickRecord(tick);
                        ticks.Add(record);
                        _lastObservedTicks[InstrumentName(tick.Symbol) + ":" + tick.TickType] = record;
                    }
                }
                foreach (var entry in slice.QuoteBars.OrderBy(entry => entry.Key.ID.ToString()))
                {
                    var record = QuoteBarRecord(entry.Value);
                    quoteBars.Add(record);
                    _lastObservedQuoteBars[InstrumentName(entry.Key)] = record;
                }
                _slices.Add(new
                {
                    time = Local(Time), utc_time = Utc(UtcTime), ticks, quote_bars = quoteBars,
                    delistings = slice.Delistings.Values.Select(delisting => new
                    {
                        instrument = InstrumentName(delisting.Symbol), symbol = delisting.Symbol.Value,
                        symbol_id = delisting.Symbol.ID.ToString(), time = Local(delisting.Time),
                        end_time = Local(delisting.EndTime), type = delisting.Type.ToString(),
                        value = delisting.Value
                    }).ToArray(),
                    state_before_strategy = State()
                });
            }

            var entryDate = _scenario == "vertical_assignment" ? new DateTime(2026, 1, 15) : Expiry;
            if (!_entrySubmitted && Time.Date == entryDate && Time.TimeOfDay >= new TimeSpan(9, 31, 0)
                && _underlying.HasData
                && (UsesMinuteQuotes ? HasCompletedEntryQuoteBar(slice, _call100.Symbol) : HasQuote(slice, _call100.Symbol))
                && (_call120 == null || _call120.HasData))
            {
                _entrySubmitted = true;
                if (_scenario == "native_itm")
                {
                    // Preserve the native tape: two contracts at limit 2 with an
                    // ask size of one. Do not manufacture a partial fill.
                    RecordSubmission(LimitOrder(_call100.Symbol, 2m, 2m,
                        tag: "native tape: buy 2 limit 2; cancel only after actual partial fill"));
                }
                else if (_scenario == "vertical_assignment")
                {
                    RecordSubmission(MarketOrder(_call120.Symbol, 1m,
                        tag: "separate margin-account vertical: long K120"));
                    RecordSubmission(MarketOrder(_call100.Symbol, -1m,
                        tag: "separate margin-account vertical: short K100"));
                }
                else
                {
                    RecordSubmission(MarketOrder(_call100.Symbol, 1m,
                        tag: UsesMinuteQuotes
                            ? "separate minute-quote control: long one K100 after first completed bar"
                            : "separate market-entry control: long one K100"));
                }
            }
            WriteReceipt();
        }

        private static bool HasQuote(Slice slice, Symbol symbol)
        {
            return slice.Ticks.TryGetValue(symbol, out var ticks)
                && ticks.Any(tick => tick.TickType == TickType.Quote && tick.AskPrice > 0m);
        }

        private bool HasCompletedEntryQuoteBar(Slice slice, Symbol symbol)
        {
            // The frozen minute experiment starts only after delivery of the
            // complete [15:55, 15:56) bar. Missing that bar is a failed input
            // observation, not permission to enter on a later substitute.
            return slice.QuoteBars.TryGetValue(symbol, out var quoteBar)
                && quoteBar.Period == TimeSpan.FromMinutes(1)
                && quoteBar.EndTime == Expiry.AddHours(15).AddMinutes(56)
                && quoteBar.EndTime <= Time
                && quoteBar.Ask != null && quoteBar.Ask.Close > 0m;
        }

        public override void OnOrderEvent(OrderEvent orderEvent)
        {
            var cancel = false;
            lock (_receiptLock)
            {
                _orderEvents.Add(EventRecord(orderEvent));
                if (_scenario == "native_itm" && orderEvent.Symbol == _call100.Symbol
                    && orderEvent.Status == OrderStatus.PartiallyFilled && !_cancelRequested)
                {
                    _cancelRequested = true;
                    cancel = true;
                }
            }
            if (cancel)
            {
                var response = Transactions.GetOrderTicket(orderEvent.OrderId)
                    .Cancel("Cancel remainder after an actual native partial fill");
                lock (_receiptLock)
                {
                    _cancelRequests.Add(new { order_id = orderEvent.OrderId, utc_time = Utc(UtcTime),
                        response = response.ToString() });
                }
            }
            WriteReceipt();
        }

        public override void OnAssignmentOrderEvent(OrderEvent assignmentEvent)
        {
            lock (_receiptLock)
            {
                // This is a second callback channel, not an additional fill.
                _assignmentEvents.Add(EventRecord(assignmentEvent));
            }
            WriteReceipt();
        }

        public override void OnEndOfAlgorithm()
        {
            _ended = true;
            WriteReceipt();
        }

        private void RecordSubmission(OrderTicket ticket)
        {
            lock (_receiptLock)
            {
                _submissions.Add(new { order_id = ticket.OrderId, instrument = InstrumentName(ticket.Symbol),
                    quantity = ticket.Quantity, status_at_return = ticket.Status.ToString(),
                    utc_time = Utc(UtcTime), state_at_return = State() });
            }
        }

        private object EventRecord(OrderEvent orderEvent)
        {
            var order = Transactions.GetOrderById(orderEvent.OrderId);
            return new
            {
                order_id = orderEvent.OrderId, event_id = orderEvent.Id,
                instrument = InstrumentName(orderEvent.Symbol), symbol = orderEvent.Symbol.Value,
                symbol_id = orderEvent.Symbol.ID.ToString(), utc_time = Utc(orderEvent.UtcTime),
                status = orderEvent.Status.ToString(), order_type = order?.Type.ToString(),
                quantity = orderEvent.Quantity, fill_quantity = orderEvent.FillQuantity,
                fill_price = orderEvent.FillPrice, fill_price_currency = orderEvent.FillPriceCurrency,
                fee = orderEvent.OrderFee.Value.Amount, fee_currency = orderEvent.OrderFee.Value.Currency,
                is_assignment = orderEvent.IsAssignment, is_in_the_money = orderEvent.IsInTheMoney,
                message = orderEvent.Message, tag = order?.Tag, state = State()
            };
        }

        private object TickRecord(Tick tick)
        {
            return new
            {
                instrument = InstrumentName(tick.Symbol), symbol = tick.Symbol.Value,
                symbol_id = tick.Symbol.ID.ToString(), tick_type = tick.TickType.ToString(),
                time = Local(tick.Time), end_time = Local(tick.EndTime),
                value = tick.Value, quantity = tick.Quantity, bid_price = tick.BidPrice,
                ask_price = tick.AskPrice, bid_size = tick.BidSize, ask_size = tick.AskSize
            };
        }

        private object QuoteBarRecord(QuoteBar quoteBar)
        {
            return new
            {
                instrument = InstrumentName(quoteBar.Symbol), symbol = quoteBar.Symbol.Value,
                symbol_id = quoteBar.Symbol.ID.ToString(),
                time = Local(quoteBar.Time), end_time = Local(quoteBar.EndTime),
                period_seconds = quoteBar.Period.TotalSeconds, receipt_utc_time = Utc(UtcTime),
                bid = quoteBar.Bid == null ? null : new
                {
                    open = quoteBar.Bid.Open, high = quoteBar.Bid.High,
                    low = quoteBar.Bid.Low, close = quoteBar.Bid.Close
                },
                ask = quoteBar.Ask == null ? null : new
                {
                    open = quoteBar.Ask.Open, high = quoteBar.Ask.High,
                    low = quoteBar.Ask.Low, close = quoteBar.Ask.Close
                },
                bid_size = quoteBar.LastBidSize, ask_size = quoteBar.LastAskSize
            };
        }

        private object State()
        {
            return new
            {
                time = Local(Time), utc_time = Utc(UtcTime),
                cash = Portfolio.Cash, unsettled_cash = Portfolio.UnsettledCash,
                cash_book = CashRecords(Portfolio.CashBook),
                unsettled_cash_book = CashRecords(Portfolio.UnsettledCashBook),
                total_portfolio_value = Portfolio.TotalPortfolioValue,
                total_holdings_value = Portfolio.TotalHoldingsValue,
                total_unrealized_profit = Portfolio.TotalUnrealizedProfit,
                total_profit = Portfolio.TotalProfit, total_fees = Portfolio.TotalFees,
                total_margin_used = Portfolio.TotalMarginUsed, margin_remaining = Portfolio.MarginRemaining,
                holdings = _instruments.ToDictionary(entry => entry.Key, entry => HoldingRecord(entry.Value))
            };
        }

        private static object CashRecords(CashBook book)
        {
            return book.ToDictionary(entry => entry.Key, entry => new
            {
                amount = entry.Value.Amount, conversion_rate = entry.Value.ConversionRate,
                value_in_account_currency = entry.Value.ValueInAccountCurrency
            });
        }

        private object HoldingRecord(Security security)
        {
            var data = security.GetLastData();
            var instrument = InstrumentName(security.Symbol);
            _lastObservedTicks.TryGetValue(instrument + ":Trade", out var observedTrade);
            _lastObservedTicks.TryGetValue(instrument + ":Quote", out var observedQuote);
            _lastObservedQuoteBars.TryGetValue(instrument, out var observedQuoteBar);
            return new
            {
                symbol = security.Symbol.Value, symbol_id = security.Symbol.ID.ToString(),
                security_type = security.Type.ToString(), quantity = security.Holdings.Quantity,
                average_price = security.Holdings.AveragePrice, current_price = security.Price,
                holdings_value = security.Holdings.HoldingsValue,
                unrealized_profit = security.Holdings.UnrealizedProfit, profit = security.Holdings.Profit,
                contract_multiplier = security.SymbolProperties.ContractMultiplier,
                has_data = security.HasData, is_tradable = security.IsTradable,
                present_in_securities = Securities.ContainsKey(security.Symbol),
                price_cache = new
                {
                    price = security.Price, close = security.Close,
                    bid_price = security.BidPrice, ask_price = security.AskPrice,
                    bid_size = security.BidSize, ask_size = security.AskSize,
                    last_data_type = data?.GetType().FullName,
                    last_data_time = data == null ? null : Local(data.Time),
                    last_data_end_time = data == null ? null : Local(data.EndTime),
                    last_strategy_observed_trade = observedTrade,
                    last_strategy_observed_quote = observedQuote,
                    last_strategy_observed_quote_bar = observedQuoteBar
                }
            };
        }

        private object ModelRecord(Security security)
        {
            var option = security as Option;
            return new
            {
                fill = security.FillModel.GetType().FullName,
                fee = security.FeeModel.GetType().FullName,
                buying_power = security.BuyingPowerModel.GetType().FullName,
                settlement = security.SettlementModel.GetType().FullName,
                portfolio = security.PortfolioModel.GetType().FullName,
                slippage = security.SlippageModel.GetType().FullName,
                exercise = option?.OptionExerciseModel.GetType().FullName,
                assignment = option?.OptionAssignmentModel.GetType().FullName,
                exercise_settlement = option?.ExerciseSettlement.ToString()
            };
        }

        private void WriteReceipt()
        {
            lock (_receiptLock)
            {
                var receipt = new
                {
                    schema_version = 1, lean_commit = LeanCommit, scenario = _scenario,
                    on_end_of_algorithm_called = _ended, algorithm_status = Status.ToString(),
                    fixture_settings = new
                    {
                        synthetic = true, data_time_zone = "America/New_York",
                        account_type = _accountType.ToString(), starting_cash = _startingCash,
                        fee_override = "ConstantFeeModel(0 USD)", fill_forward = false,
                        underlying_resolution = "Tick", option_resolution = UsesMinuteQuotes ? "Minute" : "Tick",
                        underlying_extended_market_hours = true, option_extended_market_hours = false,
                        option_style = "American", option_expiry = "2026-01-16",
                        entry_protocol = _scenario == "native_itm" ? "buy_2_limit_2_cancel_on_actual_partial_fill"
                            : _scenario == "vertical_assignment" ? "market_buy_1_K120_then_sell_1_K100"
                            : UsesMinuteQuotes ? "market_buy_1_K100_after_completed_1555_to_1556_quote_bar"
                            : "market_buy_1_K100_control",
                        manual_exercise_or_assignment = false, seeded_holdings = false
                    },
                    entry_submitted = _entrySubmitted, cancel_requested = _cancelRequested,
                    model_types = _instruments.ToDictionary(entry => entry.Key, entry => ModelRecord(entry.Value)),
                    observed_slices = _slices, last_observed_ticks = _lastObservedTicks,
                    last_observed_quote_bars = _lastObservedQuoteBars,
                    submitted_orders = _submissions, order_events = _orderEvents,
                    assignment_events = _assignmentEvents, cancel_requests = _cancelRequests,
                    orders = Transactions.GetOrders().OrderBy(order => order.Id).Select(order => new
                    {
                        order_id = order.Id, instrument = InstrumentName(order.Symbol),
                        symbol = order.Symbol.Value, symbol_id = order.Symbol.ID.ToString(),
                        type = order.Type.ToString(), status = order.Status.ToString(),
                        quantity = order.Quantity, price = order.Price, utc_time = Utc(order.Time), tag = order.Tag
                    }).ToArray(),
                    last_state = State(), end_state = _ended ? State() : null
                };
                var directory = Path.GetDirectoryName(Path.GetFullPath(_receiptPath));
                Directory.CreateDirectory(directory);
                // Retain diagnostics even when the engine cannot reach OnEndOfAlgorithm.
                var temporary = _receiptPath + ".tmp";
                File.WriteAllText(temporary, JsonConvert.SerializeObject(receipt, Formatting.Indented));
                File.Move(temporary, _receiptPath, overwrite: true);
            }
        }

        private string InstrumentName(Symbol symbol)
        {
            return _instruments.FirstOrDefault(entry => entry.Value.Symbol == symbol).Key ?? symbol.Value;
        }

        private static string Local(DateTime time) => time.ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff", CultureInfo.InvariantCulture);
        private static string Utc(DateTime time) => time.ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'", CultureInfo.InvariantCulture);
    }
}
