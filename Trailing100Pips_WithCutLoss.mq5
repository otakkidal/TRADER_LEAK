//+------------------------------------------------------------------+
//|                               Trailing100Pips_WithCutLoss.mq5    |
//|                                  Copyright 2026, Trading Assistant|
//+------------------------------------------------------------------+
#property copyright "Trading Assistant"
#property link      ""
#property version   "1.02"

#include <Trade\Trade.mqh>

//--- Input Parameters ---
input double InpStartProfitPips  = 100.0; // Profit Awal (Pips) untuk mulai SL+
input double InpTrailingStepPips = 100.0; // Kenaikan SL setiap profit kelipatan 100 Pips
input double InpLockProfitPips   = 5.0;   // Jumlah Profit (Pips) yang dikunci saat pertama kali SL+
input double InpMaxLossPips      = 300.0; // Batas Maksimal Loss (Pips) untuk Cut Loss Otomatis
input ulong  InpMagicNumber      = 0;     // Magic Number (0 = Semua posisi)
input int    InpPipMultiplier    = 10;    // Pengali Pip ke Point (Standar: 1 Pip = 10 Point)

CTrade trade;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("EA Trailing & Cut Loss Berjalan...");
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
      
      if(InpMagicNumber != 0 && PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
      
      string pos_symbol = PositionGetString(POSITION_SYMBOL);
      
      double point = SymbolInfoDouble(pos_symbol, SYMBOL_POINT);
      double pip_size = point * InpPipMultiplier;
      
      double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
      long type = PositionGetInteger(POSITION_TYPE);
      double current_sl = PositionGetDouble(POSITION_SL);
      
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
      
      // --- 1. FITUR AUTO CUT LOSS ---
      // Jika minus mencapai atau melebihi batas Max Loss (dikalikan -1 karena profit negatif)
      if(profit_pips <= -InpMaxLossPips)
        {
         if(trade.PositionClose(ticket))
           {
            PrintFormat("❌ [CUT LOSS] Posisi %d ditutup paksa karena minus menyentuh %.1f Pips", ticket, profit_pips);
           }
         else
           {
            PrintFormat("⚠️ Gagal Cut Loss tiket %d, Error code: %d", ticket, GetLastError());
           }
         continue; // Lanjut ke posisi berikutnya agar tidak mengeksekusi trailing SL di bawah ini
        }
         
      // --- 2. FITUR TRAILING SL ---
      if(profit_pips >= InpStartProfitPips)
        {
         AdjustStopLossPips(ticket, pos_symbol, type, open_price, current_sl, profit_pips, pip_size);
        }
     }
  }

//+------------------------------------------------------------------+
//| Fungsi Kalkulasi dan Modifikasi SL Berdasarkan Pips              |
//+------------------------------------------------------------------+
void AdjustStopLossPips(ulong ticket, string symbol, long type, double open_price, double current_sl, double profit_pips, double pip_size)
  {
   // Hitung berapa Pip yang harus dikunci berdasarkan kelipatan Step (100 Pips)
   double levels = MathFloor((profit_pips - InpStartProfitPips) / InpTrailingStepPips);
   double locked_pips = (levels * InpTrailingStepPips) + InpLockProfitPips;
   
   double new_sl = 0;
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   
   double min_stop_level = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL) * SymbolInfoDouble(symbol, SYMBOL_POINT);
   
   if(type == POSITION_TYPE_BUY)
     {
      new_sl = open_price + (locked_pips * pip_size);
      new_sl = NormalizeDouble(new_sl, digits);
      
      double bid_price = SymbolInfoDouble(symbol, SYMBOL_BID);
      
      // Geser SL hanya jika SL baru lebih tinggi dari SL lama
      if((current_sl == 0 || new_sl > current_sl) && (bid_price - new_sl > min_stop_level))
        {
         if(trade.PositionModify(ticket, new_sl, PositionGetDouble(POSITION_TP)))
           {
            PrintFormat("✅ [BUY] Trailing Sukses. Profit: %.1f Pips | SL Naik & Dikunci di: %.1f Pips | New SL: %f", profit_pips, locked_pips, new_sl);
           }
        }
     }
   else if(type == POSITION_TYPE_SELL)
     {
      new_sl = open_price - (locked_pips * pip_size);
      new_sl = NormalizeDouble(new_sl, digits);
      
      double ask_price = SymbolInfoDouble(symbol, SYMBOL_ASK);
      
      // Geser SL hanya jika SL baru lebih rendah dari SL lama
      if((current_sl == 0 || new_sl < current_sl) && (new_sl - ask_price > min_stop_level))
        {
         if(trade.PositionModify(ticket, new_sl, PositionGetDouble(POSITION_TP)))
           {
            PrintFormat("✅ [SELL] Trailing Sukses. Profit: %.1f Pips | SL Turun & Dikunci di: %.1f Pips | New SL: %f", profit_pips, locked_pips, new_sl);
           }
        }
     }
  }