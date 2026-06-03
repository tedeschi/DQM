//
// analyzer module producing DQM histograms for Stm subsystem
//
//


#include "art/Framework/Core/EDAnalyzer.h"
#include "art/Framework/Core/ModuleMacros.h"
#include "art/Framework/Principal/Event.h"
#include "art_root_io/TFileService.h"

#include "Offline/RecoDataProducts/inc/STMWaveformDigi.hh"
#include "Offline/RecoDataProducts/inc/STMFragmentSummary.hh"
#include "Offline/DataProducts/inc/STMChannel.hh" 
#include "Offline/Mu2eUtilities/inc/STMUtils.hh"
#include "Offline/ProditionsService/inc/ProditionsHandle.hh"
#include "Offline/RecoDataProducts/inc/STMPHDigi.hh"
#include "Offline/STMConditions/inc/STMEnergyCalib.hh"

#include "TH1F.h"

#include <string>
#include <vector>

namespace mu2e {

class DqmStm : public art::EDAnalyzer {
 public:
  struct Config {
    using Name = fhicl::Name;
    using Comment = fhicl::Comment;
    //For now using explciit tags
    fhicl::Atom<art::InputTag> rawHPGeTag{Name("rawHPGeTag"), Comment("StmWaveform rawHPGe Collection"), art::InputTag()};
    fhicl::Atom<art::InputTag> rawLaBrTag{Name("rawLaBrTag"), Comment("StmWaveform rawLaBr Collection"), art::InputTag()};
    fhicl::Atom<art::InputTag> zsHPGeTag{Name("zsHPGeTag"), Comment("StmWaveform zsHPGe Collection"), art::InputTag()}; 
    fhicl::Atom<art::InputTag> zsLaBrTag{Name("zsLaBrTag"), Comment("StmWaveform zsLaBr Collection"), art::InputTag()};
    fhicl::Atom<art::InputTag> phHPGeTag{Name("phHPGeTag"), Comment("StmDigi phHPge Collection"), art::InputTag()};
    fhicl::Atom<art::InputTag> phLaBrTag{Name("phLaBrTag"), Comment("StmDigi phLaBr Collection"), art::InputTag()};
    fhicl::Atom<art::InputTag> HPGefragSummaryTag{Name("HPGefragSummaryTag"), Comment("STM HPGe fragment summary collection"), art::InputTag()};
    fhicl::Atom<art::InputTag> LaBrfragSummaryTag{Name("LaBrfragSummaryTag"), Comment("STM LaBr fragment summary collection"), art::InputTag()};

  };
  typedef art::EDAnalyzer::Table<Config> Parameters;

  explicit DqmStm(const Parameters& conf);
  virtual ~DqmStm() {}

  virtual void beginJob();
  virtual void endJob(){};
  virtual void analyze(const art::Event& e);

private:
  Config _conf;

  //Version number tracked
  TH1D* _hVer;
  // Container and Inner Frag Counts
  TH1D* _hNContainerFrags;
  TH1D* _hNInnerFrags;

  //Raw
  TH1D* _hNRAWHPGe; //Raw Waveform size
  TH1D* _hNRAWLaBr;
  TH1D* _hNRawHPGeInnerFrags;
  TH1D* _hNRawLaBrInnerFrags;
  TH1D* _hRawHPGeADC;
  TH1D* _hRawLaBrADC;

  //ZS
  TH1D* _hNZSHPGe; //ZS Waveform size 
  TH1D* _hNZSLaBr;
  TH1D* _hNZSHPGeInnerFrags;
  TH1D* _hNZSLaBrInnerFrags;
  TH1D* _hZSHPGeADC;
  TH1D* _hZSLaBrADC;

  // PH digis
  TH1D* _hNPHHPGeInnerFrags;
  TH1D* _hNPHLaBrInnerFrags;
  TH1D* _hNPHHPGe; //Number of pulse heights for HPGe
  TH1D* _hPulseHeightHPGe; //Pulse Heigt of HPGe
  TH1D* _hNPHLaBr; //Number of pulse heights for LaBr                                                          
  TH1D* _hPulseHeightLaBr; //Pulse Heigt of LaBr
  
};
/*****************************/
  // configrues fcl to local variables
  //Will come back to simplify this with channel name
DqmStm::DqmStm(const Parameters& conf) : art::EDAnalyzer(conf), _conf(conf()) {
  mayConsume<STMPHDigiCollection>(_conf.phHPGeTag()); //reads PH from the art file given in fcl
  mayConsume<STMPHDigiCollection>(_conf.phLaBrTag());
  mayConsume<STMWaveformDigiCollection>(_conf.rawHPGeTag());
  mayConsume<STMWaveformDigiCollection>(_conf.rawLaBrTag());
  mayConsume<STMWaveformDigiCollection>(_conf.zsHPGeTag());
  mayConsume<STMWaveformDigiCollection>(_conf.zsLaBrTag());
  mayConsume<STMFragmentSummaryCollection>(_conf.HPGefragSummaryTag());
  mayConsume<STMFragmentSummaryCollection>(_conf.LaBrfragSummaryTag());
  //Will add more in time such as raw, zs, frag count etc. 
}

/*****************************************/
  // makes the hist -> working with _hNPH and _hPulseHeights
void DqmStm::beginJob() {
  art::ServiceHandle<art::TFileService> tfs;
  
  _hVer = tfs->make<TH1D>("Ver", "Version Number", 101, -0.5, 100.00);

  //histograms
  if (!_conf.rawHPGeTag().empty()){
    _hNRAWHPGe = tfs->make<TH1D>("NRawWaveformDigisHPGe", "N RAW HPGe WaveformDigis;Number of Raw WF Digis;Entries", 250, -0.5, 500.5);
    _hRawHPGeADC = tfs->make<TH1D>("RawADCHPGe","Raw HPGe ADC in Waveform;ADC;Samples", 100,0.0,3000.0); 
  }

  if (!_conf.rawLaBrTag().empty()){
    _hNRAWLaBr = tfs->make<TH1D>("NRawWaveformDigisLaBr", "N RAW LaBr WaveformDigis;Number of Raw WF Digis:Entries", 250, -0.5, 500.5);
     _hRawLaBrADC = tfs->make<TH1D>("RawADCLaBr","Raw LaBr ADC in Waveform;ADC;Samples", 100,0.0,3000.0);

  }

  if (!_conf.zsHPGeTag().empty()){
    _hNZSHPGe = tfs->make<TH1D>("NZSWaveformDigisHPGe", "N ZS HPGe WaveformDigis;Number of ZS WF Digis;Entries", 250, -0.5, 500.5);
    _hZSHPGeADC = tfs->make<TH1D>("ZSADCHPGe","ZS HPGe ADC in Waveform;ADC;Samples", 100,0.0,3000.0);
  }

  if (!_conf.zsLaBrTag().empty()){
    _hNZSLaBr = tfs->make<TH1D>("NZSWaveformDigisLaBr", "N ZS LaBr WaveformDigis;Number of ZS WF Digis;Entries", 250, -0.5, 500.5);
    _hZSLaBrADC = tfs->make<TH1D>("ZSADCLaBr","ZS LaBr ADC in Waveform;ADC;Samples", 100,0.0,3000.0);
  }

  if (!_conf.phHPGeTag().empty()){
    _hNPHHPGe = tfs->make<TH1D>("NPHDigisHPGe", "N PH HPGe Digis;Number of Pulse Heiht Digis: Entries", 20, -0.5, 30.5);
    _hPulseHeightHPGe = tfs->make<TH1D>("PulseHeightHPGe", "STM HPGe Pulse Height;Pulse Height;Entries", 1000, 0.0, 10000.0);
  }

  if (!_conf.phLaBrTag().empty()){
    _hNPHLaBr = tfs->make<TH1D>("NPHDigisLaBr", "N PH LaBr Digis;Number of Pulse Height Digis;Entries", 20, -0.5, 30.5);
    _hPulseHeightLaBr = tfs->make<TH1D>("PulseHeightLaBr", "STM LaBr Pulse Height;Pulse Height;Entries", 1000, 0.0, 10000.0);
  }

  if (!_conf.HPGefragSummaryTag().empty()&& !_conf.LaBrfragSummaryTag().empty()){
    _hNContainerFrags = tfs->make<TH1D>("NContainerFrags","N STM Container Fragments;Number of Container Frags;Events",20,-0.5,19.5);
    _hNInnerFrags = tfs->make<TH1D>("NInnerFrags", "N STM Inner Fragments;Number of Inner Frags;Events",200,-0.5,2000.5);

    _hNRawHPGeInnerFrags = tfs->make<TH1D>("NRawHPGeInnerFrags", "N Raw HPGE Inner Frags; Number of Inner Frags;Events", 200,-0.5,1000.5);
    _hNRawLaBrInnerFrags = tfs->make<TH1D>("NRawLaBrInnerFrags", "N Raw LaBr Inner Frags; Number of Inner Frags;Events", 200,-0.5,1000.5);
    _hNZSHPGeInnerFrags = tfs->make<TH1D>("NZSHPGeInnerFrags", "N ZS HPGE Inner Frags; Number of Inner Frags;Events", 200,-0.5,1000.5);
    _hNZSLaBrInnerFrags = tfs->make<TH1D>("NZSLaBrInnerFrags", "N ZS LaBr Inner Frags; Number of Inner Frags;Events", 200,-0.5,1000.5);
    _hNPHHPGeInnerFrags = tfs->make<TH1D>("NPHHPGeInnerFrags", "N PH HPGE Inner Frags; Number of Inner Frags;Events", 200,-0.5,1000.5);
    _hNPHLaBrInnerFrags = tfs->make<TH1D>("NPHLaBrInnerFrags", "N PH LaBr Inner Frags; Number of Inner Frags;Events", 200,-0.5,1000.5);

  }  
}

/************************************/
  // Filling the histograms
void DqmStm::analyze(const art::Event& event) {
  _hVer->Fill(0.0);

  if(!_conf.HPGefragSummaryTag().empty() ){
    auto summaryHandle = event.getValidHandle<STMFragmentSummaryCollection>(_conf.HPGefragSummaryTag());
    for (const auto& summary : *summaryHandle){
      _hNContainerFrags->Fill(summary.nContainerFrags());
      _hNInnerFrags->Fill(summary.nInnerFrags());
      _hNRawHPGeInnerFrags ->Fill(summary.nGoodRawFrags());
      //_hNRawLaBrInnerFrags ->Fill(summary.nRawLaBrInnerFrags());
      _hNZSHPGeInnerFrags ->Fill(summary.nGoodZSFrags());
      //_hNZSLaBrInnerFrags ->Fill(summary.nZSLaBrInnerFrags());
      _hNPHHPGeInnerFrags ->Fill(summary.nGoodPHFrags());
      //_hNPHLaBrInnerFrags ->Fill(summary.nPHLaBrInnerFrags());
    }
  }

  if(!_conf.LaBrfragSummaryTag().empty() ){
    auto summaryHandle = event.getValidHandle<STMFragmentSummaryCollection>(_conf.LaBrfragSummaryTag());
    for (const auto& summary : *summaryHandle){
      //_hNContainerFrags->Fill(summary.nContainerFrags());
      //_hNInnerFrags->Fill(summary.nInnerFrags());
      //_hNRawHPGeInnerFrags ->Fill(summary.nRawHPGeInnerFrags());
      _hNRawLaBrInnerFrags ->Fill(summary.nGoodRawFrags());
      //_hNZSHPGeInnerFrags ->Fill(summary.nZSHPGeInnerFrags());
      _hNZSLaBrInnerFrags ->Fill(summary.nGoodZSFrags());
      //_hNPHHPGeInnerFrags ->Fill(summary.nPHHPGeInnerFrags());
      _hNPHLaBrInnerFrags ->Fill(summary.nGoodPHFrags());
      
    }
  }

  if (!_conf.rawHPGeTag().empty()) {
    auto rawDigiHandle = event.getValidHandle<STMWaveformDigiCollection>(_conf.rawHPGeTag());
    const auto& rawdigis = *rawDigiHandle;
    _hNRAWHPGe->Fill(rawdigis.size());
    
    for (const auto& dg : rawdigis){
      for (const auto& adc : dg.adcs()) _hRawHPGeADC->Fill(adc);}
  }

  if (!_conf.rawLaBrTag().empty()) {
    auto rawDigiHandle = event.getValidHandle<STMWaveformDigiCollection>(_conf.rawLaBrTag());
    const auto& rawdigis = *rawDigiHandle;
    _hNRAWLaBr->Fill(rawdigis.size());

    for (const auto& dg : rawdigis){
      for (const auto& adc : dg.adcs()) _hRawLaBrADC->Fill(adc);}
  }

  if (!_conf.zsHPGeTag().empty()) {
    auto zsDigiHandle = event.getValidHandle<STMWaveformDigiCollection>(_conf.zsHPGeTag());
    const auto& zsdigis = *zsDigiHandle;
    _hNZSHPGe->Fill(zsdigis.size());

    for (const auto& dg : zsdigis){
      for (const auto& adc : dg.adcs()) _hZSHPGeADC->Fill(adc);}
  }

  if (!_conf.zsLaBrTag().empty()) {
    auto zsDigiHandle = event.getValidHandle<STMWaveformDigiCollection>(_conf.zsLaBrTag());
    const auto& zsdigis = *zsDigiHandle;
    _hNZSLaBr->Fill(zsdigis.size());

    for (const auto& dg : zsdigis){
      for (const auto& adc : dg.adcs()) _hZSLaBrADC->Fill(adc);}
  }

  if (!_conf.phHPGeTag().empty()) {
    auto phDigiHandle = event.getValidHandle<STMPHDigiCollection>(_conf.phHPGeTag());
    const auto& phDigis = *phDigiHandle;

    _hNPHHPGe->Fill(phDigis.size());

    for (const auto& phDigi: phDigis) {
      _hPulseHeightHPGe->Fill(phDigi.energy());
    }
  }

  if (!_conf.phLaBrTag().empty()) {
    auto phDigiHandle = event.getValidHandle<STMPHDigiCollection>(_conf.phLaBrTag());
    const auto& phDigis = *phDigiHandle;
    
    _hNPHLaBr->Fill(phDigis.size());
    
    for (const auto& phDigi: phDigis) {
      _hPulseHeightLaBr->Fill(phDigi.energy());
    }
  }


}
} //namespace mu2e
  
DEFINE_ART_MODULE(mu2e::DqmStm)
