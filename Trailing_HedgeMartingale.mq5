//+------------------------------------------------------------------+
//|                                Trailing_HedgeMartingale.mq5      |
//|                                  Copyright 2026, Trading Assistant|
//+------------------------------------------------------------------+
#property copyright "Trading Assistant"
#property link      ""
#property version   "1.04"

#include <Trade\Trade.mqh>

//--- Input Parameters ---
input double InpStartProfitPips     = 10.0; // Profit Awal (Pips) untuk mulai SL+
input double InpTrailingStepPips    = 10.0; // Kenaikan SL setiap profit bertambah
input double InpLockProfitPips      = 10.0; // Jumlah Profit (Pips) yang dikunci
input double InpHedgePips           = 30.0; // Batas Minus (Pips) untuk Auto Hedging
input double InpMartingaleMultiplier= 2.0;  // Pengali Lot Martingale (Misal: 2.0 atau 1.5)
input ulong  InpMagicNumber         = 0;    // Magic Number (0 = Semua posisi)
input ulong  InpHedgeMagic          = 9999; // Magic Number KHUSUS untuk posisi Hedge
input int    InpPipMultiplier       = 10;   // Pengali Pip ke Point

CTrade trade;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
     {
      Print("⚠️ PERINGATAN: Akun ini BUKAN tipe Hedging. EA tidak akan berfungsi maksimal!");
     }
   
   Print("✅ EA Trailing & Hedge-Martingale Berjalan...");
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      
      ulong current_magic = PositionGetInteger(POSITION_MAGIC);
      
      // ABAIKAN POSISI HEDGE: Agar tidak membuka hedge dari posisi hedge (mencegah loop tak terhingga)
      if(current_magic == InpHedgeMagic) continue; 
      
      // Filter Magic Number pengguna
      if(InpMagicNumber != 0 && current_magic != InpMagicNumber) continue;
      
      string pos_symbol = PositionGetString(POSITION_SYMBOL);
      double point      = SymbolInfoDouble(pos_symbol, SYMBOL_POINT);
      double pip_size   = point * InpPipMultiplier;
      
      double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
      long   type       = PositionGetInteger(POSITION_TYPE);
      double current_sl = PositionGetDouble(POSITION_SL);
      double lot_volume = PositionGetDouble(POSITION_VOLUME);
      
      double current_price = (type == POSITION_TYPE_BUY) ? SymbolInfoDouble(pos_symbol, SYMBOL_BID) : SymbolInfoDouble(pos_symbol, SYMBOL_ASK);
      
      // Hitung floating profit/loss dalam Pips
      double profit_pips = 0;
      if(type == POSITION_TYPE_BUY)
        {
         profit_pips = (current_price - open_price) / pip_size;
        }
      else if(type == POSITION_TYPE_SELL)
        {
         profit_pips = (open_price - current_price) / pip_size;
        }
      
      // --- 1. FITUR AUTO HEDGING MARTINGALE ---
      if(profit_pips <= -InpHedgePips)
        {
         if(!CheckHedgeExists(pos_symbol))
           {
            // Menghitung Lot Martingale dan memastikan sesuai dengan spesifikasi broker
            double lot_step = SymbolInfoDouble(pos_symbol, SYMBOL_VOLUME_STEP);
            double max_lot  = SymbolInfoDouble(pos_symbol, SYMBOL_VOLUME_MAX);
            
            double raw_hedge_lot = lot_volume * InpMartingaleMultiplier;
            double hedge_lot     = MathFloor(raw_hedge_lot / lot_step) * lot_step; // Pembulatan lot yang aman
            
            if(hedge_lot > max_lot) hedge_lot = max_lot; // Cegah lot melebihi batas maksimal broker
            
            trade.SetExpertMagicNumber(InpHedgeMagic); 
            
            if(type == POSITION_TYPE_BUY)
              {
               if(trade.Sell(hedge_lot, pos_symbol))
                 {
                  PrintFormat("🛡️ [HEDGE-MARTINGALE] BUY %d minus %.1f Pips. Hedge SELL %.2f Lot dibuka!", ticket, profit_pips, hedge_lot);
                 }
              }
            else if(type == POSITION_TYPE_SELL)
              {
               if(trade.Buy(hedge_lot, pos_symbol))
                 {
                  PrintFormat("🛡️ [HEDGE-MARTINGALE] SELL %d minus %.1f Pips. Hedge BUY %.2f Lot dibuka!", ticket, profit_pips, hedge_lot);
                 }
              }
            
            trade.SetExpertMagicNumber(InpMagicNumber); 
           }
         continue; 
        }
         
      // --- 2. FITUR TRAILING SL ---
      if(profit_pips >= InpStartProfitPips)
        {
         AdjustStopLossPips(ticket, pos_symbol, type, open_price, current_sl, profit_pips, pip_size);
        }
     }
  }

//+------------------------------------------------------------------+
//| Fungsi Cek Keberadaan Posisi Hedge                               |
//+------------------------------------------------------------------+
bool CheckHedgeExists(string symbol)
  {
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
        {
         if(PositionGetString(POSITION_SYMBOL) == symbol && PositionGetInteger(POSITION_MAGIC) == InpHedgeMagic)
           {
            return true; 
           }
        }
     }
   return false;
  }

//+------------------------------------------------------------------+
//| Fungsi Kalkulasi dan Modifikasi SL Berdasarkan Pips              |
//+------------------------------------------------------------------+
void AdjustStopLossPips(ulong ticket, string symbol, long type, double open_price, double current_sl, double profit_pips, double pip_size)
  {
   double levels      = MathFloor((profit_pips - InpStartProfitPips) / InpTrailingStepPips);
   double locked_pips = (levels * InpTrailingStepPips) + InpLockProfitPips;
   
   double new_sl = 0;
   int digits    = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double min_stop_level = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL) * SymbolInfoDouble(symbol, SYMBOL_POINT);
   
   if(type == POSITION_TYPE_BUY)
     {
      new_sl = open_price + (locked_pips * pip_size);
      new_sl = NormalizeDouble(new_sl, digits);
      double bid_price = SymbolInfoDouble(symbol, SYMBOL_BID);
      
      if((current_sl == 0 || new_sl > current_sl) && (bid_price - new_sl > min_stop_level))
        {
         if(trade.PositionModify(ticket, new_sl, PositionGetDouble(POSITION_TP)))
           {
            PrintFormat("✅ [BUY] Trailing. Profit: %.1f Pips | Locked: %.1f Pips | SL Baru: %f", profit_pips, locked_pips, new_sl);
           }
        }
     }
   else if(type == POSITION_TYPE_SELL)
     {
      new_sl = open_price - (locked_pips * pip_size);
      new_sl = NormalizeDouble(new_sl, digits);
      double ask_price = SymbolInfoDouble(symbol, SYMBOL_ASK);
      
      if((current_sl == 0 || new_sl < current_sl) && (new_sl - ask_price > min_stop_level))
        {
         if(trade.PositionModify(ticket, new_sl, PositionGetDouble(POSITION_TP)))
           {
            PrintFormat("✅ [SELL] Trailing. Profit: %.1f Pips | Locked: %.1f Pips | SL Baru: %f", profit_pips, locked_pips, new_sl);
           }
        }
     }
  }